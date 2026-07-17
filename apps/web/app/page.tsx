"use client";

import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";

type Citation = {
  document_id: string;
  filename: string;
  score: number;
  source_url?: string | null;
};

type Message = {
  role: "user" | "assistant";
  content: string;
  rewritten?: string;
  citations?: Citation[];
  messageId?: string;
};

type LoginForm = { tenantSlug: string; username: string; password: string };

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
const tokenStorageKey = "enterprise-rag-access-token";

function safeUrl(value: string) {
  try {
    const resolved = new URL(value, new URL(apiBase).origin);
    return resolved.protocol === "http:" || resolved.protocol === "https:" ? resolved.toString() : null;
  } catch {
    return null;
  }
}

function inlineMarkdown(text: string): ReactNode[] {
  const pattern = /(!\[([^\]]*)\]\(([^)]+)\)|\[([^\]]+)\]\(([^)]+)\)|`([^`]+)`|\*\*([^*]+)\*\*)/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
    if (match[2] !== undefined && match[3] !== undefined) {
      const url = safeUrl(match[3]);
      nodes.push(url
        ? <img className="markdown-image" key={match.index} src={url} alt={match[2]} loading="lazy" />
        : match[0]);
    } else if (match[4] !== undefined && match[5] !== undefined) {
      const url = safeUrl(match[5]);
      nodes.push(url
        ? <a key={match.index} href={url} target="_blank" rel="noreferrer">{match[4]}</a>
        : match[4]);
    } else if (match[6] !== undefined) {
      nodes.push(<code key={match.index}>{match[6]}</code>);
    } else if (match[7] !== undefined) {
      nodes.push(<strong key={match.index}>{match[7]}</strong>);
    }
    cursor = pattern.lastIndex;
  }

  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function MarkdownContent({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const rendered: ReactNode[] = [];
  const codeLines: string[] = [];
  let inCodeBlock = false;
  let listItems: string[] = [];

  function flushList(key: number) {
    if (!listItems.length) return;
    rendered.push(
      <ul key={`list-${key}`}>
        {listItems.map((item, index) => <li key={index}>{inlineMarkdown(item)}</li>)}
      </ul>,
    );
    listItems = [];
  }

  for (const [index, line] of lines.entries()) {
    if (line.trim().startsWith("```")) {
      flushList(index);
      if (inCodeBlock) {
        rendered.push(<pre key={`code-${index}`}><code>{codeLines.join("\n")}</code></pre>);
        codeLines.length = 0;
      }
      inCodeBlock = !inCodeBlock;
      continue;
    }
    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }
    const listMatch = line.match(/^\s*[-*]\s+(.+)$/);
    if (listMatch) {
      listItems.push(listMatch[1]);
      continue;
    }
    flushList(index);
    if (!line.trim()) continue;

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const children = inlineMarkdown(heading[2]);
      if (heading[1].length === 1) rendered.push(<h2 key={index}>{children}</h2>);
      else if (heading[1].length === 2) rendered.push(<h3 key={index}>{children}</h3>);
      else rendered.push(<h4 key={index}>{children}</h4>);
      continue;
    }

    const imageOnly = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
    if (imageOnly) {
      const url = safeUrl(imageOnly[2]);
      rendered.push(url
        ? <img className="markdown-image" key={index} src={url} alt={imageOnly[1]} loading="lazy" />
        : <p key={index}>{line}</p>);
      continue;
    }
    rendered.push(<p key={index}>{inlineMarkdown(line)}</p>);
  }

  flushList(lines.length);
  if (inCodeBlock || codeLines.length) {
    rendered.push(<pre key="code-final"><code>{codeLines.join("\n")}</code></pre>);
  }
  return <div className="markdown-content">{rendered}</div>;
}

export default function HomePage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [query, setQuery] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [login, setLogin] = useState<LoginForm>({ tenantSlug: "default", username: "", password: "" });
  const [authError, setAuthError] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);

  const authHeaders = useMemo(() => token ? { Authorization: `Bearer ${token}` } : {}, [token]);

  useEffect(() => {
    const stored = window.localStorage.getItem(tokenStorageKey);
    if (!stored) {
      setAuthReady(true);
      return;
    }
    fetch(`${apiBase}/security/me`, { headers: { Authorization: `Bearer ${stored}` } })
      .then((response) => {
        if (!response.ok) throw new Error("登录已过期");
        setToken(stored);
      })
      .catch(() => window.localStorage.removeItem(tokenStorageKey))
      .finally(() => setAuthReady(true));
  }, []);

  function clearAuthentication() {
    window.localStorage.removeItem(tokenStorageKey);
    setToken(null);
    setSessionId(null);
    setMessages([]);
  }

  async function authenticatedFetch(input: string, init: RequestInit = {}) {
    const headers = new Headers(init.headers);
    Object.entries(authHeaders).forEach(([name, value]) => headers.set(name, value));
    const response = await fetch(input, { ...init, headers });
    if (response.status === 401) clearAuthentication();
    return response;
  }

  async function submitLogin(event: FormEvent) {
    event.preventDefault();
    setAuthBusy(true);
    setAuthError("");
    try {
      const response = await fetch(`${apiBase}/security/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: login.username,
          password: login.password,
          tenant_slug: login.tenantSlug,
        }),
      });
      if (!response.ok) {
        throw new Error(response.status === 401 ? "用户名、密码或租户不正确" : await response.text());
      }
      const data = await response.json();
      window.localStorage.setItem(tokenStorageKey, data.access_token);
      setToken(data.access_token);
      setLogin((current) => ({ ...current, password: "" }));
    } catch (error) {
      setAuthError(String(error));
    } finally {
      setAuthBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!query.trim() || busy || !token) return;
    const userMessage: Message = { role: "user", content: query.trim() };
    const history = messages.map(({ role, content }) => ({ role, content }));
    setMessages((current) => [...current, userMessage]);
    setQuery("");
    setBusy(true);
    try {
      const response = await authenticatedFetch(`${apiBase}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: userMessage.content, history, session_id: sessionId }),
      });
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      setSessionId(data.session_id);
      setMessages((current) => [...current, {
        role: "assistant",
        content: data.answer,
        rewritten: data.rewritten_query,
        citations: data.citations,
        messageId: data.message_id,
      }]);
    } catch (error) {
      setMessages((current) => [...current, { role: "assistant", content: `请求失败：${String(error)}` }]);
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    if (!token) return;
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    try {
      const response = await authenticatedFetch(`${apiBase}/documents/upload`, {
        method: "POST",
        body: form,
      });
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
    const response = await authenticatedFetch(`${apiBase}/messages/${messageId}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value, reason }),
    });
    if (!response.ok) alert(`反馈提交失败：${await response.text()}`);
  }

  if (!authReady) {
    return <main className="auth-shell"><div className="auth-card">正在验证登录状态…</div></main>;
  }

  if (!token) {
    return (
      <main className="auth-shell">
        <form className="auth-card" onSubmit={submitLogin}>
          <p className="eyebrow">ENTERPRISE RAG</p>
          <h1>登录知识库</h1>
          <p className="auth-help">使用所属租户的账号登录。首次部署请先通过安全引导接口创建管理员。</p>
          <label>租户标识<input value={login.tenantSlug} onChange={(event) => setLogin({ ...login, tenantSlug: event.target.value })} required /></label>
          <label>用户名<input value={login.username} onChange={(event) => setLogin({ ...login, username: event.target.value })} autoComplete="username" required /></label>
          <label>密码<input type="password" value={login.password} onChange={(event) => setLogin({ ...login, password: event.target.value })} autoComplete="current-password" required /></label>
          {authError && <div className="auth-error">{authError}</div>}
          <button type="submit" disabled={authBusy}>{authBusy ? "登录中…" : "登录"}</button>
        </form>
      </main>
    );
  }

  return (
    <main>
      <header>
        <div><p className="eyebrow">ENTERPRISE RAG</p><h1>内部技术知识助手</h1></div>
        <div className="header-actions">
          <label className="upload">
            {uploading ? "处理中…" : "上传文档"}
            <input type="file" accept=".docx,.pdf,.md,.markdown,.txt,.html,.htm" disabled={uploading} onChange={(event) => event.target.files?.[0] && upload(event.target.files[0])} />
          </label>
          <button className="logout" onClick={clearAuthentication}>退出登录</button>
        </div>
      </header>
      <section className="chat">
        {messages.length === 0 && <div className="empty"><h2>从企业知识库中查找答案</h2><p>上传技术文档后，可以询问配置、部署、排障和接口使用问题。</p></div>}
        {messages.map((message, index) => (
          <article className={message.role} key={`${message.role}-${index}`}>
            <div className="role">{message.role === "user" ? "你" : "知识助手"}</div>
            {message.rewritten && <div className="rewrite">改写查询：{message.rewritten}</div>}
            <MarkdownContent content={message.content} />
            {message.citations && message.citations.length > 0 && <div className="citations">
              {message.citations.map((citation) => {
                const url = citation.source_url ? safeUrl(citation.source_url) : null;
                return url
                  ? <a key={citation.document_id} href={url} target="_blank" rel="noreferrer">{citation.filename} · {citation.score.toFixed(3)}</a>
                  : <span key={citation.document_id}>{citation.filename} · {citation.score.toFixed(3)}</span>;
              })}
            </div>}
            {message.messageId && <div className="feedback"><button onClick={() => feedback(message.messageId!, 1)}>有帮助</button><button onClick={() => feedback(message.messageId!, -1)}>需改进</button></div>}
          </article>
        ))}
      </section>
      <form className="composer" onSubmit={submit}>
        <textarea value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入技术问题…" rows={3} />
        <button type="submit" disabled={busy}>{busy ? "检索生成中…" : "发送"}</button>
      </form>
    </main>
  );
}
