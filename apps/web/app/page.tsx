"use client";

import Image from "next/image";
import {
  type CSSProperties,
  type FormEvent,
  type ReactNode,
  useCallback,
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

type ChatSession = {
  session_id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
};

type SessionMessage = {
  message_id: string;
  query: string;
  answer: string;
  rewritten_query: string;
  citations: Citation[];
  timings_ms: TimingMap;
};

const apiBase =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
const tokenStorageKey = "enterprise-rag-access-token";
const activeSessionStorageKey = "enterprise-rag-active-session";

const timingOrder = [
  "retrieval_router",
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
  retrieval_router: "Retrieval router",
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
  const [currentAnswerIndex, setCurrentAnswerIndex] = useState(0);
  const [answerIndexDraft, setAnswerIndexDraft] = useState("");
  const [answerNavigatorHovered, setAnswerNavigatorHovered] = useState(false);
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionActionId, setSessionActionId] = useState<string | null>(null);
  const [renameSession, setRenameSession] = useState<ChatSession | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [feedbackMessageId, setFeedbackMessageId] = useState<string | null>(null);
  const [feedbackReason, setFeedbackReason] = useState("");
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [deleteSession, setDeleteSession] = useState<ChatSession | null>(null);

  const endRef = useRef<HTMLDivElement>(null);
  const followRef = useRef(true);
  const programmaticScrollRef = useRef(false);
  const lastScrollYRef = useRef(0);
  const touchYRef = useRef<number | null>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const feedbackInputRef = useRef<HTMLTextAreaElement>(null);
  const authHeaders = useMemo(
    () => (token ? { Authorization: `Bearer ${token}` } : {}),
    [token],
  );
  const totalAnswers = useMemo(
    () => messages.filter((message) => message.role === "user").length,
    [messages],
  );
  const questionIndexByMessage = useMemo(() => {
    const indexes = new Map<number, number>();
    let questionIndex = 0;
    messages.forEach((message, messageIndex) => {
      if (message.role === "user") {
        questionIndex += 1;
        indexes.set(messageIndex, questionIndex);
      }
    });
    return indexes;
  }, [messages]);
  const currentLyric = lyrics[lyricLine] ?? "";
  const visibleLyric = Array.from(currentLyric)
    .slice(0, lyricChar)
    .join("");

  const jumpToAnswer = useCallback(
    (requestedIndex: number) => {
      if (!totalAnswers) return;
      const targetIndex = Math.min(Math.max(Math.trunc(requestedIndex), 1), totalAnswers);
      const target = document.querySelector<HTMLElement>(
        `[data-question-index="${targetIndex}"]`,
      );
      if (!target) return;
      followRef.current = false;
      setCurrentAnswerIndex(targetIndex);
      setAnswerIndexDraft(String(targetIndex));
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    [totalAnswers],
  );

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
    const updateCurrentAnswer = () => {
      const anchors = Array.from(
        document.querySelectorAll<HTMLElement>("[data-question-index]"),
      );
      if (!anchors.length) {
        setCurrentAnswerIndex(0);
        return;
      }
      if (busy && followRef.current && totalAnswers) {
        setCurrentAnswerIndex(totalAnswers);
        return;
      }
      const referenceLine = 120;
      let visibleIndex = Number(anchors[0].dataset.questionIndex ?? 1);
      for (const anchor of anchors) {
        if (anchor.getBoundingClientRect().top <= referenceLine) {
          visibleIndex = Number(anchor.dataset.questionIndex ?? visibleIndex);
        } else {
          break;
        }
      }
      setCurrentAnswerIndex(visibleIndex);
    };

    const onScroll = () => {
      const currentScrollY = window.scrollY;
      if (
        busy &&
        !programmaticScrollRef.current &&
        currentScrollY < lastScrollYRef.current
      ) {
        followRef.current = false;
      }
      lastScrollYRef.current = currentScrollY;
      updateCurrentAnswer();
    };
    const onWheel = (event: WheelEvent) => {
      if (busy && event.deltaY < 0) followRef.current = false;
    };
    const onTouchStart = (event: TouchEvent) => {
      touchYRef.current = event.touches[0]?.clientY ?? null;
    };
    const onTouchMove = (event: TouchEvent) => {
      const currentY = event.touches[0]?.clientY;
      if (
        busy &&
        currentY !== undefined &&
        touchYRef.current !== null &&
        currentY > touchYRef.current
      ) {
        followRef.current = false;
      }
      touchYRef.current = currentY ?? null;
    };

    lastScrollYRef.current = window.scrollY;
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("wheel", onWheel, { passive: true });
    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: true });
    updateCurrentAnswer();
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("wheel", onWheel);
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
    };
  }, [busy, messages, totalAnswers]);

  useEffect(() => {
    if (!totalAnswers) {
      setCurrentAnswerIndex(0);
      setAnswerIndexDraft("");
      return;
    }
    setCurrentAnswerIndex((value) =>
      busy && followRef.current
        ? totalAnswers
        : Math.min(Math.max(value || 1, 1), totalAnswers),
    );
  }, [busy, totalAnswers]);

  useEffect(() => {
    if (!answerNavigatorHovered || !totalAnswers) return;

    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable ||
        event.ctrlKey ||
        event.metaKey ||
        event.altKey
      ) {
        return;
      }
      const key = event.key.toLowerCase();
      if (key !== "w" && key !== "s") return;
      event.preventDefault();
      const baseIndex = currentAnswerIndex || 1;
      jumpToAnswer(key === "w" ? baseIndex - 1 : baseIndex + 1);
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [answerNavigatorHovered, currentAnswerIndex, jumpToAnswer, totalAnswers]);

  useEffect(() => {
    if (!busy || !followRef.current) return;

    programmaticScrollRef.current = true;
    endRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
    const frame = window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        lastScrollYRef.current = window.scrollY;
        programmaticScrollRef.current = false;
      });
    });
    return () => window.cancelAnimationFrame(frame);
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
    window.localStorage.removeItem(activeSessionStorageKey);
    setToken(null);
    setSessionId(null);
    setMessages([]);
    setChatSessions([]);
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

  const resetConversation = useCallback(() => {
    setSessionId(null);
    setMessages([]);
    setTimings({});
    setPipelineStatus("--");
    setCurrentAnswerIndex(0);
    setAnswerIndexDraft("");
    followRef.current = true;
  }, []);

  const openSession = useCallback(
    async (targetSessionId: string, accessToken = token) => {
      if (!accessToken) return;
      setSessionActionId(targetSessionId);
      try {
        const response = await fetch(
          `${apiBase}/chat/sessions/${targetSessionId}/detail`,
          { headers: { Authorization: `Bearer ${accessToken}` } },
        );
        if (response.status === 401) {
          clearAuthentication();
          return;
        }
        if (!response.ok) throw new Error(await response.text());
        const data = await response.json();
        const restored: Message[] = [];
        (data.messages as SessionMessage[]).forEach((item) => {
          restored.push({ role: "user", content: item.query });
          restored.push({
            role: "assistant",
            content: item.answer,
            rewritten:
              item.rewritten_query.trim() === item.query.trim()
                ? "/"
                : item.rewritten_query,
            citations: item.citations,
            messageId: item.message_id,
          });
        });
        setSessionId(targetSessionId);
        setMessages(restored);
        setTimings(
          data.messages.length
            ? data.messages[data.messages.length - 1].timings_ms
            : {},
        );
        setPipelineStatus(data.messages.length ? "Completed" : "--");
        setCurrentAnswerIndex(data.messages.length);
        setAnswerIndexDraft("");
        followRef.current = false;
        window.localStorage.setItem(activeSessionStorageKey, targetSessionId);
        window.requestAnimationFrame(() => window.scrollTo({ top: 0 }));
      } finally {
        setSessionActionId(null);
      }
    },
    [token],
  );

  const loadSessions = useCallback(
    async (accessToken = token, restoreActive = false) => {
      if (!accessToken) return;
      setSessionsLoading(true);
      try {
        const response = await fetch(`${apiBase}/chat/sessions`, {
          headers: { Authorization: `Bearer ${accessToken}` },
        });
        if (response.status === 401) {
          clearAuthentication();
          return;
        }
        if (!response.ok) throw new Error(await response.text());
        const data = await response.json();
        const sessions = data.sessions as ChatSession[];
        setChatSessions(sessions);
        if (restoreActive && sessions.length) {
          const storedId = window.localStorage.getItem(activeSessionStorageKey);
          const target = sessions.some((item) => item.session_id === storedId)
            ? storedId
            : sessions[0].session_id;
          if (target) await openSession(target, accessToken);
        }
      } finally {
        setSessionsLoading(false);
      }
    },
    [openSession, token],
  );

  function startNewChat() {
    if (busy) return;
    window.localStorage.removeItem(activeSessionStorageKey);
    resetConversation();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openRenameDialog(item: ChatSession) {
    setRenameSession(item);
    setRenameTitle(item.title);
    window.requestAnimationFrame(() => renameInputRef.current?.select());
  }

  function closeRenameDialog() {
    if (renameSession && sessionActionId === renameSession.session_id) return;
    setRenameSession(null);
    setRenameTitle("");
  }

  async function renameChatSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!renameSession) return;
    const title = renameTitle.trim();
    if (!title || title === renameSession.title) {
      closeRenameDialog();
      return;
    }

    setSessionActionId(renameSession.session_id);
    try {
      const response = await authenticatedFetch(
        `${apiBase}/chat/sessions/${renameSession.session_id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title }),
        },
      );
      if (!response.ok) return;
      const renamed = (await response.json()) as ChatSession;
      setChatSessions((current) =>
        current.map((session) =>
          session.session_id === renamed.session_id ? renamed : session,
        ),
      );
      setRenameSession(null);
      setRenameTitle("");
    } finally {
      setSessionActionId(null);
    }
  }
  function openDeleteDialog(item: ChatSession) {
    setDeleteSession(item);
  }

  function closeDeleteDialog() {
    if (deleteSession && sessionActionId === deleteSession.session_id) return;
    setDeleteSession(null);
  }

  async function deleteChatSession() {
    if (!deleteSession) return;
    const target = deleteSession;
    setSessionActionId(target.session_id);
    try {
      const response = await authenticatedFetch(
        `${apiBase}/chat/sessions/${target.session_id}`,
        { method: "DELETE" },
      );
      if (!response.ok) return;
      const remaining = chatSessions.filter(
        (session) => session.session_id !== target.session_id,
      );
      setChatSessions(remaining);
      setDeleteSession(null);
      if (sessionId !== target.session_id) return;
      window.localStorage.removeItem(activeSessionStorageKey);
      resetConversation();
      if (remaining.length) await openSession(remaining[0].session_id);
    } finally {
      setSessionActionId(null);
    }
  }
  useEffect(() => {
    if (!token) return;
    void loadSessions(token, true);
  }, [loadSessions, token]);

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
    setCurrentAnswerIndex(totalAnswers + 1);
    setAnswerIndexDraft("");
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
          const activeSessionId = String(event.session_id);
          setSessionId(activeSessionId);
          window.localStorage.setItem(activeSessionStorageKey, activeSessionId);
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
                    rewritten:
                      String(event.rewritten_query ?? "").trim() === text.trim()
                        ? "/"
                        : String(event.rewritten_query ?? ""),
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
          const completedSessionId = String(event.session_id);
          const completedAt = new Date().toISOString();
          setPipelineStatus("Completed");
          setSessionId(completedSessionId);
          setChatSessions((current) => {
            const existing = current.find(
              (item) => item.session_id === completedSessionId,
            );
            const completedSession: ChatSession = existing
              ? {
                  ...existing,
                  message_count: existing.message_count + 1,
                  updated_at: completedAt,
                }
              : {
                  session_id: completedSessionId,
                  title: text.slice(0, 80),
                  message_count: 1,
                  created_at: completedAt,
                  updated_at: completedAt,
                };
            return [
              completedSession,
              ...current.filter(
                (item) => item.session_id !== completedSessionId,
              ),
            ];
          });
          if (event.timings_ms) setTimings(event.timings_ms as TimingMap);
          setMessages((current) =>
            current.map((message, index) =>
              index === assistantIndex
                ? {
                    ...message,
                    rewritten:
                      String(event.rewritten_query ?? "").trim() === text.trim()
                        ? "/"
                        : String(
                            event.rewritten_query ?? message.rewritten ?? "",
                          ),
                    citations: event.citations as Citation[],
                    messageId: String(event.message_id),
                  }
                : message,
            ),
          );
          void loadSessions();
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

  function openFeedbackDialog(messageId: string) {
    setFeedbackMessageId(messageId);
    setFeedbackReason("");
    window.requestAnimationFrame(() => feedbackInputRef.current?.focus());
  }

  function closeFeedbackDialog() {
    if (feedbackBusy) return;
    setFeedbackMessageId(null);
    setFeedbackReason("");
  }

  async function sendFeedback(messageId: string, value: number, reason = "") {
    const response = await authenticatedFetch(
      `${apiBase}/messages/${messageId}/feedback`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value, reason }),
      },
    );

    if (!response.ok) return false;
    setMessages((current) =>
      current.map((message) =>
        message.messageId === messageId
          ? { ...message, feedbackState: "fading" }
          : message,
      ),
    );
    return true;
  }

  async function submitFeedbackReason(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!feedbackMessageId) return;
    setFeedbackBusy(true);
    try {
      const submitted = await sendFeedback(
        feedbackMessageId,
        -1,
        feedbackReason.trim(),
      );
      if (submitted) {
        setFeedbackMessageId(null);
        setFeedbackReason("");
      }
    } finally {
      setFeedbackBusy(false);
    }
  }
  if (!authReady) {
    return (
      <main className="auth-shell">
        <div className="auth-loading">
          <span className="brand-mark">?</span>
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
        <aside className="session-rail" aria-label="Conversation history">
          <div className="session-rail-heading">
            <div>
              <p className="eyebrow">History</p>
              <h2>Conversations</h2>
            </div>
            <button
              className="new-chat-button"
              type="button"
              onClick={startNewChat}
              disabled={busy}
              aria-label="New chat"
            >
              +
            </button>
          </div>
          <div className="session-list">
            {sessionsLoading && !chatSessions.length ? (
              <p className="session-empty">Loading...</p>
            ) : chatSessions.length ? (
              chatSessions.map((item) => (
                <div
                  className={`session-item ${sessionId === item.session_id ? "active" : ""}`}
                  key={item.session_id}
                >
                  <button
                    className="session-open"
                    type="button"
                    onClick={() => void openSession(item.session_id)}
                    disabled={busy || sessionActionId === item.session_id}
                  >
                    <span className="session-title">{item.title}</span>
                    <span className="session-meta">
                      {item.message_count} {item.message_count === 1 ? "answer" : "answers"}
                    </span>
                  </button>
                  <div className="session-actions">
                    <button
                      type="button"
                      onClick={() => openRenameDialog(item)}
                      aria-label={`Rename ${item.title}`}
                      title="Rename"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => openDeleteDialog(item)}
                      aria-label={`Delete ${item.title}`}
                      title="Delete"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <p className="session-empty">No conversations yet</p>
            )}
          </div>
          <p className="session-rail-note">Your conversations are saved automatically.</p>
        </aside>

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
                  <button type="button" onClick={() => setQuery("Was it I who missed freedom all along, or was freedom never something that required waiting?")}>
                    Freedom
                  </button>
                  <button type="button" onClick={() => setQuery("Is faith a truth meant to be believed, or merely an illusion meant to sustain me through this life?")}>
                    Faith
                  </button>
                  <button type="button" onClick={() => setQuery("Is loneliness a prison where no one understands you, or a pilgrimage each soul is born to walk alone?")}>
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
                  data-question-index={questionIndexByMessage.get(index)}
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
                        <span>Was this helpful ?</span>
                        <button type="button" onClick={() => void sendFeedback(message.messageId!, 1)}>
                          Helpful
                        </button>
                        <button type="button" onClick={() => openFeedbackDialog(message.messageId!)}>
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

        {renameSession && (
          <div
            className="rename-dialog-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) closeRenameDialog();
            }}
          >
            <form
              className="rename-dialog"
              role="dialog"
              aria-modal="true"
              aria-labelledby="rename-dialog-title"
              onSubmit={renameChatSession}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  closeRenameDialog();
                }
              }}
            >
              <div className="rename-dialog-heading">
                <p className="eyebrow">Conversation</p>
                <h2 id="rename-dialog-title">Rename</h2>
              </div>
              <input
                ref={renameInputRef}
                value={renameTitle}
                onChange={(event) => setRenameTitle(event.target.value)}
                maxLength={80}
                autoFocus
                aria-label="Conversation name"
              />
              <div className="rename-dialog-actions">
                <button type="button" onClick={closeRenameDialog}>
                  Cancel
                </button>
                <button
                  className="rename-confirm"
                  type="submit"
                  disabled={
                    !renameTitle.trim() ||
                    sessionActionId === renameSession.session_id
                  }
                >
                  {sessionActionId === renameSession.session_id
                    ? "Saving..."
                    : "Save"}
                </button>
              </div>
            </form>
          </div>
        )}
        {feedbackMessageId && (
          <div
            className="rename-dialog-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) closeFeedbackDialog();
            }}
          >
            <form
              className="rename-dialog feedback-dialog"
              role="dialog"
              aria-modal="true"
              aria-labelledby="feedback-dialog-title"
              onSubmit={submitFeedbackReason}
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  closeFeedbackDialog();
                }
              }}
            >
              <div className="rename-dialog-heading">
                <p className="eyebrow">Feedback</p>
                <h2 id="feedback-dialog-title">What needs work?</h2>
              </div>
              <textarea
                ref={feedbackInputRef}
                value={feedbackReason}
                onChange={(event) => setFeedbackReason(event.target.value)}
                maxLength={500}
                rows={4}
                autoFocus
                placeholder="Share your improvement suggestion..."
                aria-label="Improvement suggestion"
              />
              <div className="rename-dialog-actions">
                <button type="button" onClick={closeFeedbackDialog}>
                  Cancel
                </button>
                <button
                  className="rename-confirm"
                  type="submit"
                  disabled={feedbackBusy}
                >
                  {feedbackBusy ? "Sending..." : "Submit"}
                </button>
              </div>
            </form>
          </div>
        )}
        {deleteSession && (
          <div
            className="rename-dialog-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) closeDeleteDialog();
            }}
          >
            <div
              className="rename-dialog delete-dialog"
              role="alertdialog"
              aria-modal="true"
              aria-labelledby="delete-dialog-title"
              aria-describedby="delete-dialog-description"
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  event.preventDefault();
                  closeDeleteDialog();
                }
              }}
            >
              <div className="rename-dialog-heading">
                <p className="eyebrow">Conversation</p>
                <h2 id="delete-dialog-title">Delete this conversation?</h2>
              </div>
              <p id="delete-dialog-description" className="delete-dialog-copy">
                “{deleteSession.title}” will be permanently deleted. This action
                cannot be undone.
              </p>
              <div className="rename-dialog-actions">
                <button type="button" onClick={closeDeleteDialog} autoFocus>
                  Cancel
                </button>
                <button
                  className="delete-confirm"
                  type="button"
                  onClick={() => void deleteChatSession()}
                  disabled={sessionActionId === deleteSession.session_id}
                >
                  {sessionActionId === deleteSession.session_id
                    ? "Deleting..."
                    : "Delete"}
                </button>
              </div>
            </div>
          </div>
        )}
        <div className="right-rail">
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

          <aside
            className="answer-navigator"
            aria-label="Answer navigator"
            onMouseEnter={() => setAnswerNavigatorHovered(true)}
            onMouseLeave={() => setAnswerNavigatorHovered(false)}
          >
            <span className="answer-navigator-label">Answers</span>
            <div className="answer-navigator-count">
              {totalAnswers ? (
                <>
                  <input
                    aria-label="Current answer number"
                    inputMode="numeric"
                    min={1}
                    max={totalAnswers}
                    type="number"
                    value={
                      answerIndexDraft || String(currentAnswerIndex || 1)
                    }
                    onChange={(event) =>
                      setAnswerIndexDraft(event.currentTarget.value)
                    }
                    onFocus={(event) => {
                      setAnswerIndexDraft(String(currentAnswerIndex || 1));
                      event.currentTarget.select();
                    }}
                    onBlur={() => setAnswerIndexDraft("")}
                    onKeyDown={(event) => {
                      if (event.key !== "Enter") return;
                      event.preventDefault();
                      jumpToAnswer(Number(event.currentTarget.value));
                      event.currentTarget.blur();
                    }}
                  />
                  <span>/</span>
                  <span>{totalAnswers}</span>
                </>
              ) : (
                <span>-/-</span>
              )}
            </div>
            <span className="answer-navigator-hint">Hover : W / S</span>
          </aside>
        </div>
      </div>
    </main>
  );
}
