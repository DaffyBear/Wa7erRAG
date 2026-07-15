import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Enterprise RAG",
  description: "Production-oriented enterprise knowledge assistant",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
