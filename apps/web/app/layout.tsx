import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Wa7er RAG",
  description: "knowledge assistant",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
