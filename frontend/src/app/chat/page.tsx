"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { chatApi } from "@/lib/api";
import { userStorage } from "@/lib/storage";

interface Message {
  id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  isStreaming?: boolean;
}

const QUICK_ACTIONS = [
  "今天的饮食和训练计划是什么？",
  "我这周的执行情况怎么样？",
  "今天应该怎么补蛋白质？",
  "帮我看看今天训练强度安排。",
];

export default function ChatPage() {
  const router = useRouter();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "我是你的 Carbon Coach。你可以问我今日计划、训练执行、饮食建议和周复盘问题。",
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);

  useEffect(() => {
    if (!userStorage.getUserId()) {
      router.push("/login");
    }
  }, [router]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const sendMessage = useCallback(
    async (content?: string) => {
      const text = (content ?? input).trim();
      if (!text || isLoading) {
        return;
      }

      const userId = userStorage.getUserId();
      if (!userId) {
        router.push("/login");
        return;
      }

      setMessages((prev) => [
        ...prev,
        { role: "user", content: text },
        { role: "assistant", content: "", isStreaming: true },
      ]);
      setInput("");
      setIsLoading(true);

      try {
        let fullContent = "";

        for await (const chunk of chatApi.streamMessage(userId, text, sessionId || undefined)) {
          if (chunk.type === "session") {
            setSessionId(chunk.session_id);
            continue;
          }

          if (chunk.type === "content") {
            fullContent += chunk.content;
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = {
                ...next[next.length - 1],
                content: fullContent,
              };
              return next;
            });
            continue;
          }

          if (chunk.type === "done") {
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = {
                ...next[next.length - 1],
                id: chunk.message_id,
                isStreaming: false,
              };
              return next;
            });
          }
        }
      } catch (error) {
        console.error(error);
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = {
            role: "assistant",
            content: "连接失败了，请稍后再试。",
            isStreaming: false,
          };
          return next;
        });
      } finally {
        setIsLoading(false);
      }
    },
    [input, isLoading, router, sessionId],
  );

  return (
    <div className="h-[calc(100vh-6rem)] p-4 max-w-4xl mx-auto flex flex-col gap-4">
      <div className="flex items-center justify-between py-2">
        <div>
          <h1 className="text-2xl font-black text-primary">AI 私教</h1>
          <p className="text-xs font-bold uppercase text-muted-foreground tracking-widest">
            Carbon Coach
          </p>
        </div>
        <button
          onClick={() => {
            setMessages([
              {
                role: "assistant",
                content: "新对话已开始，你想先聊饮食、训练还是周复盘？",
              },
            ]);
            setSessionId(null);
          }}
          className="px-4 py-2 text-sm font-medium text-primary hover:bg-primary/10 rounded-lg transition-colors"
        >
          新对话
        </button>
      </div>

      <div className="flex-1 glass-card p-6 flex flex-col overflow-hidden bg-white/70">
        <div ref={scrollRef} className="flex-1 overflow-y-auto no-scrollbar space-y-4">
          {messages.map((message, index) => {
            const isUser = message.role === "user";
            return (
              <div
                key={`${message.role}-${index}`}
                className={`flex ${isUser ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-5 py-3 shadow-sm text-sm leading-relaxed whitespace-pre-wrap ${
                    isUser
                      ? "bg-primary text-white rounded-br-sm"
                      : "bg-white text-foreground rounded-bl-sm border border-gray-100"
                  }`}
                >
                  {message.content}
                  {message.isStreaming && (
                    <span className="inline-block w-2 h-4 bg-primary/60 ml-1 animate-pulse" />
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {messages.length <= 2 && (
          <div className="my-4 flex gap-2 flex-wrap justify-center">
            {QUICK_ACTIONS.map((action) => (
              <button
                key={action}
                onClick={() => void sendMessage(action)}
                disabled={isLoading}
                className="px-4 py-2 bg-white/80 hover:bg-white border border-gray-100 rounded-full text-sm font-medium transition-all hover:shadow-md disabled:opacity-50"
              >
                {action}
              </button>
            ))}
          </div>
        )}

        <div className="mt-2 relative">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !isLoading) {
                void sendMessage();
              }
            }}
            placeholder="问我今天怎么吃、怎么练..."
            disabled={isLoading}
            className="w-full h-14 pl-6 pr-14 rounded-full bg-white/50 border-2 border-transparent focus:border-primary/20 focus:bg-white outline-none transition-all shadow-inner disabled:opacity-60"
          />
          <button
            onClick={() => void sendMessage()}
            disabled={!input.trim() || isLoading}
            className="absolute right-2 top-2 w-10 h-10 bg-primary text-white rounded-full flex items-center justify-center shadow-lg hover:scale-110 active:scale-95 transition-all disabled:opacity-50 disabled:scale-100"
          >
            {isLoading ? "..." : "→"}
          </button>
        </div>
      </div>
    </div>
  );
}
