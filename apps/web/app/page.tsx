"use client";

import { FormEvent, useState } from "react";

type Citation = { document_id: string; filename: string; score: number; source_url?: string | null };
type Message = { role: "user" | "assistant"; content: string; rewritten?: string; citations?: Citation[]; messageId?: string };

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export default function HomePage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [query, setQuery] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!query.trim() || busy) return;
    const userMessage: Message = { role: "user", content: query.trim() };
    const history = messages.map(({ role, content }) => ({ role, content }));
    setMessages((current) => [...current, userMessage]);
    setQuery("");
    setBusy(true);
    try {
      const response = await fetch(`${apiBase}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: userMessage.content, history, session_id: sessionId }),
      });
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      setSessionId(data.session_id);
      setMessages((current) => [...current, {
        role: "assistant", content: data.answer, rewritten: data.rewritten_query,
        citations: data.citations, messageId: data.message_id,
      }]);
    } catch (error) {
      setMessages((current) => [...current, { role: "assistant", content: `请求失败：${String(error)}` }]);
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    try {
      const response = await fetch(`${apiBase}/documents/upload`, { method: "POST", body: form });
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      alert(`入库完成：${result.filename}，${result.chunk_count} 个切片`);
    } catch (error) {
      alert(`上传失败：${String(error)}`);
    } finally {
      setUploading(false);
    }
  }

  async function feedback(messageId: string, value: number) {
    const reason = value === -1 ? prompt("请填写点踩原因，这将进入 Bad Case 数据集：") ?? "" : "";
    await fetch(`${apiBase}/messages/${messageId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value, reason }),
    });
  }

  return (
    <main>
      <header>
        <div><p className="eyebrow">ENTERPRISE RAG</p><h1>内部技术知识助手</h1></div>
        <label className="upload">
          {uploading ? "处理中…" : "上传文档"}
          <input type="file" accept=".docx,.md,.txt,.html,.htm" disabled={uploading} onChange={(event) => event.target.files?.[0] && upload(event.target.files[0])} />
        </label>
      </header>
      <section className="chat">
        {messages.length === 0 && <div className="empty"><h2>从企业知识库中查找答案</h2><p>上传技术文档后，可以询问配置、部署、排障和接口使用问题。</p></div>}
        {messages.map((message, index) => (
          <article className={message.role} key={`${message.role}-${index}`}>
            <div className="role">{message.role === "user" ? "你" : "知识助手"}</div>
            {message.rewritten && <div className="rewrite">改写查询：{message.rewritten}</div>}
            <div className="content">{message.content}</div>
            {message.citations && message.citations.length > 0 && <div className="citations">
              {message.citations.map((citation) => <span key={citation.document_id}>{citation.filename} · {citation.score.toFixed(3)}</span>)}
            </div>}
            {message.messageId && <div className="feedback"><button onClick={() => feedback(message.messageId!, 1)}>有帮助</button><button onClick={() => feedback(message.messageId!, -1)}>需改进</button></div>}
          </article>
        ))}
      </section>
      <form onSubmit={submit}>
        <textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入技术问题…" rows={3} />
        <button type="submit" disabled={busy}>{busy ? "检索生成中…" : "发送"}</button>
      </form>
    </main>
  );
}