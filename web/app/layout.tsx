import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BTC Signal Agent",
  description: "Next.js dashboard for the local BTC Binance signal agent"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
