"use client";

import Image from "next/image";
import {
  type CSSProperties,
  type FormEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

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
  feedbackState?: "fading";
};

type LoginForm = {
  tenantSlug: string;
  username: string;
  password: string;
};

type TimingMap = Record<string, number>;

const apiBase =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
const tokenStorageKey = "enterprise-rag-access-token";

const timingOrder = [
  "rewrite",
  "hyde_generation",
  "retrieval_rerank",
  "first_token",
  "generation",
  "cache_hit",
  "direct_answer_route",
  "total",
];

const timingLabels: Record<string, string> = {
  rewrite: "Rewrite",
  hyde_generation: "HyDE",
  retrieval_rerank: "Retrieval / Rerank",
  first_token: "First token",
  generation: "Answer generation",
  cache_hit: "Cache hit",
  direct_answer_route: "Direct answer",
  total: "Total",
};

function safeUrl(value: string) {
  try {
    const resolved = new URL(value, new URL(apiBase).origin);
    return resolved.protocol === "http:" || resolved.protocol === "https:"
      ? resolved.toString()
      : null;
  } catch {
    return null;
  }
}

function formatDuration(value: number | undefined, timings: TimingMap) {
  if (value === undefined) {
    return timings.total !== undefined ? "/" : "--";
  }
  return `${(value / 1000).toFixed(value < 10 ? 4 : 2)} s`;
}

function inlineMarkdown(text: string): ReactNode[] {
  const pattern =
    /(\[文档\s*(\d+)\]|!\[([^\]]*)\]\(([^)]+)\)|\[([^\]]+)\]\(([^)]+)\)|`([^`]+)`|\*\*([^*]+)\*\*)/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(text.slice(cursor, match.index));
    }

    if (match[2]) {
      nodes.push(
        <sup className="document-citation" key={match.index}>
          {match[2]}
        </sup>,
      );
    } else if (match[3] && match[4]) {
      const url = safeUrl(match[4]);
      nodes.push(
        url ? (
          <img
            className="markdown-image"
            key={match.index}
            src={url}
            alt={match[3]}
            loading="lazy"
          />
        ) : (
          match[0]
        ),
      );
    } else if (match[5] && match[6]) {
      const url = safeUrl(match[6]);
      nodes.push(
        url ? (
          <a key={match.index} href={url} target="_blank" rel="noreferrer">
            {match[5]}
          </a>
        ) : (
          match[5]
        ),
      );
    } else if (match[7]) {
      nodes.push(<code key={match.index}>{match[7]}</code>);
    } else if (match[8]) {
      nodes.push(<strong key={match.index}>{match[8]}</strong>);
    }

    cursor = pattern.lastIndex;
  }

  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }

  return nodes;
}

function MarkdownContent({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const rendered: ReactNode[] = [];
  const codeLines: string[] = [];
  let inCodeBlock = false;
  let listItems: string[] = [];

  const flushList = (key: number) => {
    if (!listItems.length) return;

    rendered.push(
      <ul key={`list-${key}`}>
        {listItems.map((item, index) => (
          <li key={index}>{inlineMarkdown(item)}</li>
        ))}
      </ul>,
    );
    listItems = [];
  };

  lines.forEach((line, index) => {
    if (line.trim().startsWith("```")) {
      flushList(index);

      if (inCodeBlock) {
        rendered.push(
          <pre key={`code-${index}`}>
            <code>{codeLines.join("\n")}</code>
          </pre>,
        );
        codeLines.length = 0;
      }

      inCodeBlock = !inCodeBlock;
      return;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      return;
    }

    const listMatch = line.match(/^\s*[-*]\s+(.+)$/);
    if (listMatch) {
      listItems.push(listMatch[1]);
      return;
    }

    flushList(index);
    if (!line.trim()) return;

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const tag =
        heading[1].length === 1
          ? "h2"
          : heading[1].length === 2
            ? "h3"
            : "h4";
      const Heading = tag as "h2" | "h3" | "h4";
      rendered.push(
        <Heading key={index}>{inlineMarkdown(heading[2])}</Heading>,
      );
      return;
    }

    rendered.push(<p key={index}>{inlineMarkdown(line)}</p>);
  });

  flushList(lines.length);
  if (inCodeBlock) {
    rendered.push(
      <pre key="code-final">
        <code>{codeLines.join("\n")}</code>
      </pre>,
    );
  }

  return <div className="markdown-content">{rendered}</div>;
}

export default function HomePage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [query, setQuery] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [login, setLogin] = useState<LoginForm>({
    tenantSlug: "default",
    username: "",
    password: "",
  });
  const [authError, setAuthError] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [timings, setTimings] = useState<TimingMap>({});
  const [pipelineStatus, setPipelineStatus] = useState("--");
  const [lyrics, setLyrics] = useState<string[]>([]);
  const [lyricLine, setLyricLine] = useState(0);
  const [lyricChar, setLyricChar] = useState(0);
  const [sendSplash, setSendSplash] = useState(false);

  const endRef = useRef<HTMLDivElement>(null);
  const followRef = useRef(true);
  const authHeaders = useMemo(
    () => (token ? { Authorization: `Bearer ${token}` } : {}),
    [token],
  );
  const currentLyric = lyrics[lyricLine] ?? "";
  const visibleLyric = Array.from(currentLyric)
    .slice(0, lyricChar)
    .join("");

  useEffect(() => {
    fetch("/content/lyrics.md")
      .then((response) => (response.ok ? response.text() : ""))
      .then((text) => {
        setLyrics(
          text
            .split(/\r?\n/)
            .map((line) => line.trim())
            .filter(Boolean),
        );
      })
      .catch(() => setLyrics([]));
  }, []);

  useEffect(() => {
    if (!lyrics.length) return;

    const isComplete = lyricChar >= Array.from(currentLyric).length;
    const timer = window.setTimeout(
      () => {
        if (isComplete) {
          setLyricLine((value) => (value + 1) % lyrics.length);
          setLyricChar(0);
        } else {
          setLyricChar((value) => value + 1);
        }
      },
      isComplete ? 500 : 110,
    );

    return () => window.clearTimeout(timer);
  }, [currentLyric, lyricChar, lyricLine, lyrics]);

  useEffect(() => {
    const onScroll = () => {
      followRef.current =
        document.documentElement.scrollHeight -
          window.innerHeight -
          window.scrollY <
        80;
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (busy && followRef.current) {
      endRef.current?.scrollIntoView({ behavior: "auto" });
    }
  }, [busy, messages]);

  useEffect(() => {
    const stored = window.localStorage.getItem(tokenStorageKey);
    if (!stored) {
      setAuthReady(true);
      return;
    }

    fetch(`${apiBase}/security/me`, {
      headers: { Authorization: `Bearer ${stored}` },
    })
      .then((response) => {
        if (!response.ok) throw new Error("Login expired");
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
    setTimings({});
    setPipelineStatus("--");
  }

  async function authenticatedFetch(input: string, init: RequestInit = {}) {
    const headers = new Headers(init.headers);
    Object.entries(authHeaders).forEach(([key, value]) => {
      headers.set(key, value);
    });

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
        throw new Error(
          response.status === 401
            ? "Invalid username, password, or tenant"
            : await response.text(),
        );
      }

      const data = await response.json();
      window.localStorage.setItem(tokenStorageKey, data.access_token);
      setToken(data.access_token);
      setLogin((value) => ({ ...value, password: "" }));
    } catch (error) {
      setAuthError(String(error));
    } finally {
      setAuthBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!query.trim() || busy || !token) return;

    const text = query.trim();
    const history = messages.map(({ role, content }) => ({ role, content }));
    const assistantIndex = messages.length + 1;

    followRef.current = true;
    setMessages((current) => [
      ...current,
      { role: "user", content: text },
      { role: "assistant", content: "" },
    ]);
    setQuery("");
    setTimings({});
    setPipelineStatus("Preparing");
    setBusy(true);

    try {
      const response = await authenticatedFetch(`${apiBase}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: text,
          history,
          session_id: sessionId,
        }),
      });

      if (!response.ok) throw new Error(await response.text());
      if (!response.body) throw new Error("娴忚鍣ㄤ笉鏀寔娴佸紡鍝嶅簲");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      const applyEvent = (event: Record<string, unknown>) => {
        if (event.type === "start") {
          setSessionId(String(event.session_id));
          setPipelineStatus("Processing");
          return;
        }

        if (event.type === "rewrite_delta") {
          setPipelineStatus("Rewriting");
          const value = String(event.content ?? "");
          setMessages((current) =>
            current.map((message, index) =>
              index === assistantIndex
                ? { ...message, rewritten: (message.rewritten ?? "") + value }
                : message,
            ),
          );
          return;
        }

        if (event.type === "rewrite") {
          setMessages((current) =>
            current.map((message, index) =>
              index === assistantIndex
                ? {
                    ...message,
                    rewritten: String(event.rewritten_query ?? ""),
                  }
                : message,
            ),
          );
          return;
        }

        if (event.type === "timing") {
          const stage = String(event.stage ?? "");
          if (stage) {
            setTimings((current) => ({
              ...current,
              [stage]: Number(event.duration_ms ?? 0),
            }));
          }
          return;
        }

        if (event.type === "delta") {
          setPipelineStatus("Generating response");
          const value = String(event.content ?? "");
          setMessages((current) =>
            current.map((message, index) =>
              index === assistantIndex
                ? { ...message, content: message.content + value }
                : message,
            ),
          );
          return;
        }

        if (event.type === "done") {
          setPipelineStatus("Completed");
          setSessionId(String(event.session_id));
          if (event.timings_ms) setTimings(event.timings_ms as TimingMap);
          setMessages((current) =>
            current.map((message, index) =>
              index === assistantIndex
                ? {
                    ...message,
                    rewritten: String(
                      event.rewritten_query ?? message.rewritten ?? "",
                    ),
                    citations: event.citations as Citation[],
                    messageId: String(event.message_id),
                  }
                : message,
            ),
          );
          return;
        }

        if (event.type === "error") {
          throw new Error(String(event.message ?? "娴佸紡璇锋眰澶辫触"));
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        lines
          .filter((line) => line.trim())
          .forEach((line) => applyEvent(JSON.parse(line)));

        if (done) break;
      }

      if (buffer.trim()) applyEvent(JSON.parse(buffer));
    } catch (error) {
      setPipelineStatus("Failed");
      setMessages((current) =>
        current.map((message, index) =>
          index === assistantIndex
            ? {
                ...message,
                content: message.content || `璇锋眰澶辫触锛?{String(error)}`,
              }
            : message,
        ),
      );
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
      alert(`Ingestion completed: ${result.filename}, ${result.chunk_count} chunks`);
    } catch (error) {
      alert(`Upload failed: ${String(error)}`);
    } finally {
      setUploading(false);
    }
  }

  async function feedback(messageId: string, value: number) {
    const reason =
      value === -1 ? window.prompt("Please share your feedback") ?? "" : "";
    const response = await authenticatedFetch(
      `${apiBase}/messages/${messageId}/feedback`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value, reason }),
      },
    );

    if (!response.ok) return;
    setMessages((current) =>
      current.map((message) =>
        message.messageId === messageId
          ? { ...message, feedbackState: "fading" }
          : message,
      ),
    );
  }

  if (!authReady) {
    return (
      <main className="auth-shell">
        <div className="auth-loading">
          <span className="brand-mark">W</span>
          <p>Preparing workspace...</p>
        </div>
      </main>
    );
  }

  if (!token) {
    return (
      <main className="auth-shell">
        <section className="auth-stage">
          <div className="auth-story">
            <div className="brand-lockup">
              <span className="brand-mark">🤪</span>
              <span>Wa7er RAG</span>
            </div>
            <div className="auth-story-copy">
              <p className="eyebrow"></p>
              <h1>
                <span className="universe-glow">Better than being</span>
                <br />
                <span className="universe-glow">each other's world,</span>
                <br />
                <span className="universe-glow">be your own</span>
                <br />
                <span className="universe-glow">universe.</span>
              </h1>
              <p></p>
            </div>
            <p className="auth-footnote"></p>
          </div>

          <form className="auth-card" onSubmit={submitLogin}>
            <div className="auth-card-heading">
              <p className="eyebrow">WELCOME BACK!</p>
              <h2>Login</h2>
              <p className="auth-help"></p>
            </div>
            <div className="auth-fields">
              <label>
                Tenant
                <input
                  value={login.tenantSlug}
                  onChange={(event) =>
                    setLogin({ ...login, tenantSlug: event.target.value })
                  }
                  required
                />
              </label>
              <label>
                Username
                <input
                  value={login.username}
                  onChange={(event) =>
                    setLogin({ ...login, username: event.target.value })
                  }
                  autoComplete="username"
                  required
                />
              </label>
              <label>
                Password
                <input
                  type="password"
                  value={login.password}
                  onChange={(event) =>
                    setLogin({ ...login, password: event.target.value })
                  }
                  autoComplete="current-password"
                  required
                />
              </label>
            </div>
            {authError && <div className="auth-error">{authError}</div>}
            <button className="primary-button" type="submit" disabled={authBusy}>
              {authBusy ? "Signing in..." : "Sign in"}
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark">🤪</span>
          <span>Wa7er RAG</span>
        </div>
        <div className="topbar-custom">
          <span className="topbar-custom-mark">♬</span>
          <span className="topbar-custom-text">
            {visibleLyric}
            <span className="lyric-caret" />
          </span>
        </div>
        <div className="header-actions">
          <label className="upload secondary-button">
            <span>{uploading ? "Uploading..." : "Upload"}</span>
            <input
              type="file"
              accept=".docx,.pdf,.md,.markdown,.txt,.html,.htm"
              disabled={uploading}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) upload(file);
              }}
            />
          </label>
          <button className="text-button" onClick={clearAuthentication}>
            Sign out
          </button>
        </div>
      </header>

      <section className="workspace-heading">
        <p className="eyebrow"></p>
        <h1>Wa7er's Planet</h1>
        <p>Only then will you stop treating your growth as an accident.</p>
      </section>

      <div className="conversation-layout">
        <div className="conversation-main">
          <section className="chat" aria-live="polite">
            {messages.length === 0 && (
              <div className="empty">
                <div className="empty-symbol">
                  <Image src="/logo.png" alt="Wa7er" width={74} height={74} priority />
                </div>
                <p className="eyebrow">Start a soulful Q&amp;A session.</p>
                <h2>Your question?</h2>
                <p>You can ask something that touches the soul.</p>
                <div className="prompt-examples">
                  <button type="button" onClick={() => setQuery("How do I configure the system?")}>
                    Freedom
                  </button>
                  <button type="button" onClick={() => setQuery("What should I pay attention to?")}>
                    Faith
                  </button>
                  <button type="button" onClick={() => setQuery("Help me find the relevant document.")}>
                    Solitude
                  </button>
                </div>
              </div>
            )}

            <div className="message-list">
              {messages.map((message, index) => (
                <article
                  className={`message ${message.role}`}
                  key={`${message.role}-${index}`}
                >
                  <div className="message-meta">
                    <span className="avatar">{message.role === "user" ? "🤣" : "😅"}</span>
                    <span className="role">{message.role === "user" ? "You" : "Message"}</span>
                  </div>
                  <div className="message-body">
                    {message.rewritten && (
                      <div className="rewrite">
                        <span>Query rewrite</span>
                        {message.rewritten}
                      </div>
                    )}
                    <MarkdownContent content={message.content} />
                    {message.citations?.length ? (
                      <div className="source-block">
                        <p>Sources</p>
                        <div className="citations">
                          {message.citations.map((citation, citationIndex) => {
                            const url = citation.source_url
                              ? safeUrl(citation.source_url)
                              : null;
                            const label = `Document ${citationIndex + 1}`;
                            const content = (
                              <>
                                <span>
                                  {label} · {citation.filename}
                                </span>
                                <small>{citation.score.toFixed(3)}</small>
                              </>
                            );

                            return url ? (
                              <a
                                key={citation.document_id}
                                href={url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                {content}
                              </a>
                            ) : (
                              <div className="citation-item" key={citation.document_id}>
                                {content}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ) : null}
                    {message.messageId && (
                      <div
                        className={`feedback ${
                          message.feedbackState === "fading" ? "fading" : ""
                        }`}
                      >
                        <span>Was this helpful?</span>
                        <button type="button" onClick={() => feedback(message.messageId!, 1)}>
                          Helpful
                        </button>
                        <button type="button" onClick={() => feedback(message.messageId!, -1)}>
                          Needs work
                        </button>
                      </div>
                    )}
                  </div>
                </article>
              ))}
            </div>
            <div ref={endRef} className="stream-anchor" />
          </section>

          <form className="composer" onSubmit={submit}>
            <div className="composer-field">
              <textarea
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" || event.ctrlKey || event.nativeEvent.isComposing) {
                    return;
                  }
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }}
                placeholder="Enter a prompt…"
                rows={2}
              />
              <span>The answer will be provided based on the database.</span>
            </div>
            <button
              className="send-button"
              type="submit"
              disabled={busy || !query.trim()}
              aria-label="Send"
            >
              <span
                className={query ? "send-wave active" : "send-wave"}
                style={
                  {
                    "--send-fill": `${Math.min(Array.from(query).length, 10) * 10}%`,
                  } as CSSProperties
                }
              />
              <span className="send-button-content">↑</span>
            </button>
          </form>
        </div>

        <aside className="timing-panel" aria-live="polite">
          <div className="timing-panel-heading">
            <div>
              <p className="eyebrow">Reply Metrics</p>
              <h2>Pipeline</h2>
            </div>
            <span className={`timing-status ${busy ? "active" : ""} ${pipelineStatus === "Completed" ? "completed" : ""}`}>
              {pipelineStatus}
            </span>
          </div>
          <div className="timing-table">
            {timingOrder.map((stage) => (
              <div
                className={`timing-row ${stage === "total" ? "total" : ""}`}
                key={stage}
              >
                <span>{timingLabels[stage]}</span>
                <strong>{formatDuration(timings[stage], timings)}</strong>
              </div>
            ))}
          </div>
          <p className="timing-note">
            Each response records the time spent across the retrieval pipeline.
          </p>
        </aside>
      </div>
    </main>
  );
}
