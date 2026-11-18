// Builds the same five stories for each direction. The mockups are HTML strings; Html renders them.
import { appPage, phone, signInPage } from "../markup.js";

export const Html = ({ html }) => <div dangerouslySetInnerHTML={{ __html: html }} />;

export function variantStories(variant) {
  return {
    Conversation: { render: () => <Html html={appPage(variant, { screen: "conversation" })} /> },
    NewChat: { name: "New chat", render: () => <Html html={appPage(variant, { screen: "empty" })} /> },
    SignIn: { name: "Sign in", render: () => <Html html={signInPage(variant)} /> },
    Phone: { render: () => <Html html={phone(appPage(variant, { screen: "conversation", mobile: true }))} /> },
    PhoneMenu: { name: "Phone, chats open", render: () => <Html html={phone(appPage(variant, { screen: "conversation", mobile: true, drawer: true }))} /> },
  };
}
