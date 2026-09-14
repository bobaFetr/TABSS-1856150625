import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TABSS — търговски симулации",
  description: "Самостоятелна изследователска среда за търговски симулации и мандати",
  icons: {
    icon: "/icon.png",
    shortcut: "/icon.png",
    apple: "/icon.png"
  }
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="bg">
      <body>{children}</body>
    </html>
  );
}
