"""Student-facing pieces: Cognito with Google sign-in and the allowlist triggers, the HTTP API
with a JWT authorizer in front of the chat Lambda, the streaming chat function, and the static
chat page on CloudFront."""

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, SecretValue, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from constructs import Construct

from .config import DeployConfig

TOKEN_LIFETIME = Duration.hours(1)  # also how long a removed student keeps access, at most
# AWS-published Lambda Web Adapter (github.com/awslabs/aws-lambda-web-adapter), v1.1.0, arm64.
WEB_ADAPTER_LAYER = "arn:aws:lambda:{region}:753240598075:layer:LambdaAdapterLayerArm64:30"


class StudentAccess(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        config: DeployConfig,
        backend_dir: Path,
        web_dir: Path,
        table: dynamodb.ITableV2,
        chat: lambda_.IFunction,
        stream_code: Path,
        chat_role: iam.IRole,
        chat_environment: dict[str, str],
    ):
        super().__init__(scope, construct_id)
        stack = Stack.of(self)

        triggers = lambda_.Function(
            self,
            "AllowlistTriggers",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="auth_triggers.handler.lambda_handler",
            code=lambda_.Code.from_asset(str(backend_dir), exclude=["chat_api", "chat_api/**", "requirements.txt", "**/__pycache__"]),
            timeout=Duration.seconds(5),  # Cognito's trigger limit
            environment={"TABLE_NAME": table.table_name},
            log_group=logs.LogGroup(self, "TriggerLogs", retention=logs.RetentionDays.THREE_MONTHS, removal_policy=RemovalPolicy.DESTROY),
        )
        triggers.add_to_role_policy(iam.PolicyStatement(actions=["dynamodb:GetItem"], resources=[table.table_arn]))

        pool = cognito.UserPool(
            self,
            "Users",
            feature_plan=cognito.FeaturePlan.LITE,
            self_sign_up_enabled=False,  # Google federation only, gated by the allowlist
            sign_in_aliases=cognito.SignInAliases(email=True),
            account_recovery=cognito.AccountRecovery.NONE,
            lambda_triggers=cognito.UserPoolTriggers(pre_sign_up=triggers, pre_token_generation=triggers),
            removal_policy=RemovalPolicy.DESTROY,  # user records only mirror Google accounts
        )
        domain = pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=config.auth_domain_prefix),
            managed_login_version=cognito.ManagedLoginVersion.CLASSIC_HOSTED_UI,
        )

        providers = [cognito.UserPoolClientIdentityProvider.COGNITO]
        google = None
        if config.google_client_id:
            google = cognito.UserPoolIdentityProviderGoogle(
                self,
                "Google",
                user_pool=pool,
                client_id=config.google_client_id,
                client_secret_value=SecretValue.secrets_manager(config.google_secret_name, json_field="client_secret"),
                scopes=["openid", "email", "profile"],
                attribute_mapping=cognito.AttributeMapping(
                    email=cognito.ProviderAttribute.GOOGLE_EMAIL,
                    email_verified=cognito.ProviderAttribute.GOOGLE_EMAIL_VERIFIED,
                    fullname=cognito.ProviderAttribute.GOOGLE_NAME,
                ),
            )
            providers = [cognito.UserPoolClientIdentityProvider.GOOGLE]

        site_bucket = s3.Bucket(
            self,
            "Site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        headers = cloudfront.ResponseHeadersPolicy(
            self,
            "SecurityHeaders",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                # Wildcards rather than exact hosts: the API's CORS config already references
                # this distribution, so referencing the API here would be a dependency cycle.
                content_security_policy=cloudfront.ResponseHeadersContentSecurityPolicy(
                    content_security_policy=(
                        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                        f"connect-src 'self' https://*.execute-api.{stack.region}.amazonaws.com "
                        f"https://*.lambda-url.{stack.region}.on.aws https://*.amazoncognito.com; "
                        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
                    ),
                    override=True,
                ),
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(override=True),
                frame_options=cloudfront.ResponseHeadersFrameOptions(frame_option=cloudfront.HeadersFrameOption.DENY, override=True),
                referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=cloudfront.HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN, override=True
                ),
                strict_transport_security=cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=Duration.days(365), include_subdomains=True, override=True
                ),
            ),
        )
        custom = (
            {
                "domain_names": [config.domain_name],
                "certificate": acm.Certificate.from_certificate_arn(self, "Certificate", config.certificate_arn),
            }
            if config.domain_name
            else {}
        )
        distribution = cloudfront.Distribution(
            self,
            "Cdn",
            **custom,
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=headers,
            ),
        )
        cloudfront_url = f"https://{distribution.distribution_domain_name}/"
        site_url = f"https://{config.domain_name}/" if config.domain_name else cloudfront_url
        # Both addresses stay valid for sign-in, so old links keep working after a domain is added.
        site_urls = list(dict.fromkeys([site_url, cloudfront_url, *config.extra_web_origins_slash]))

        client = pool.add_client(
            "Web",
            generate_secret=False,  # public browser client; PKCE protects the code exchange
            supported_identity_providers=providers,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
                callback_urls=site_urls,
                logout_urls=site_urls,
            ),
            id_token_validity=TOKEN_LIFETIME,
            access_token_validity=TOKEN_LIFETIME,
            refresh_token_validity=Duration.days(7),
            prevent_user_existence_errors=True,
            enable_token_revocation=True,
        )
        if google:
            client.node.add_dependency(google)

        # Answers stream from a function URL: API Gateway can't stream responses. The URL is
        # public, so server.py verifies the Cognito ID token on every request itself.
        stream = lambda_.Function(
            self,
            "ChatStream",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="run.sh",
            code=lambda_.Code.from_asset(str(stream_code)),
            role=chat_role,
            layers=[lambda_.LayerVersion.from_layer_version_arn(self, "WebAdapter", WEB_ADAPTER_LAYER.format(region=stack.region))],
            memory_size=512,
            timeout=Duration.seconds(120),
            reserved_concurrent_executions=config.lambda_reserved_concurrency or None,
            log_group=logs.LogGroup(self, "StreamLogs", retention=logs.RetentionDays.THREE_MONTHS, removal_policy=RemovalPolicy.DESTROY),
            environment={
                **chat_environment,
                "AWS_LAMBDA_EXEC_WRAPPER": "/opt/bootstrap",
                "AWS_LWA_INVOKE_MODE": "response_stream",
                "AWS_LWA_PORT": "8080",
                "USER_POOL_ID": pool.user_pool_id,
                "WEB_CLIENT_ID": client.user_pool_client_id,
            },
        )
        stream_url = stream.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            invoke_mode=lambda_.InvokeMode.RESPONSE_STREAM,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=[url.rstrip("/") for url in site_urls],
                allowed_methods=[lambda_.HttpMethod.POST],
                allowed_headers=["authorization", "content-type"],
                max_age=Duration.days(1),
            ),
        )

        api = apigw.HttpApi(
            self,
            "Api",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=[url.rstrip("/") for url in site_urls],
                allow_methods=[apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.POST, apigw.CorsHttpMethod.PATCH, apigw.CorsHttpMethod.DELETE],
                allow_headers=["authorization", "content-type"],
                max_age=Duration.days(1),
            ),
        )
        # Unauthenticated calls are rejected here, before any Lambda runs (so they cost nothing).
        authorizer = authorizers.HttpJwtAuthorizer(
            "Cognito",
            f"https://cognito-idp.{stack.region}.amazonaws.com/{pool.user_pool_id}",
            jwt_audience=[client.user_pool_client_id],
        )
        # 29 s is API Gateway's ceiling; the chat Lambda bounds its Claude call to fit inside it.
        integration = integrations.HttpLambdaIntegration("Chat", chat, timeout=Duration.seconds(29))
        routes = {
            "/chat": [apigw.HttpMethod.POST],
            "/feedback": [apigw.HttpMethod.POST],
            "/chats": [apigw.HttpMethod.GET],
            "/chats/{id}": [apigw.HttpMethod.GET, apigw.HttpMethod.PATCH, apigw.HttpMethod.DELETE],
            "/chats/stop": [apigw.HttpMethod.POST],
        }
        for path, methods in routes.items():
            api.add_routes(path=path, methods=methods, integration=integration, authorizer=authorizer)
        stage = api.default_stage.node.default_child
        stage.default_route_settings = apigw.CfnStage.RouteSettingsProperty(
            throttling_rate_limit=config.api_rate_per_second, throttling_burst_limit=config.api_burst
        )

        auth_domain = f"https://{domain.domain_name}.auth.{stack.region}.amazoncognito.com"
        s3deploy.BucketDeployment(
            self,
            "DeploySite",
            destination_bucket=site_bucket,
            distribution=distribution,
            sources=[
                s3deploy.Source.asset(str(web_dir)),
                s3deploy.Source.json_data(
                    "config.json",
                    {
                        "apiUrl": api.api_endpoint,
                        "streamUrl": stream_url.url,
                        "chatRetentionDays": config.chat_retention_days,
                        "authDomain": auth_domain,
                        "clientId": client.user_pool_client_id,
                        "redirectUri": site_url,
                    },
                ),
            ],
        )

        self.user_pool = pool
        CfnOutput(stack, "WebUrl", value=site_url)
        CfnOutput(stack, "ApiUrl", value=api.api_endpoint)
        CfnOutput(stack, "StreamUrl", value=stream_url.url)
        CfnOutput(stack, "UserPoolId", value=pool.user_pool_id)
        CfnOutput(stack, "WebClientId", value=client.user_pool_client_id)
        CfnOutput(stack, "GoogleRedirectUri", value=f"{auth_domain}/oauth2/idpresponse")
