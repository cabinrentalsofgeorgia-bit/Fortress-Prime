"use client";

import { useState, useRef, useEffect } from "react";
import { useConversations, useMessagesByPhone, useSendMessage, useGuest, useReservations, useMessageTemplates } from "@/lib/hooks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Separator } from "@/components/ui/separator";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  MessageSquare,
  Send,
  Bot,
  User,
  Phone,
  Mail,
  CalendarDays,
  Home,
  Search,
  FileText,
  CheckCheck,
  Check,
} from "lucide-react";
import { ChatSkeleton } from "@/components/skeletons";
import type { ConversationThread } from "@/lib/types";

export default function MessagesPage() {
  const [selectedThread, setSelectedThread] = useState<ConversationThread | null>(null);
  const [reply, setReply] = useState("");
  const [threadSearch, setThreadSearch] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const { data: conversations, isLoading: convoLoading } = useConversations();
  const { data: messages } = useMessagesByPhone(selectedThread?.guest_phone ?? "");
  const { data: guest } = useGuest(selectedThread?.guest_id ?? "");
  const { data: reservations } = useReservations();
  const { data: templates } = useMessageTemplates();
  const sendMessage = useSendMessage();

  const guestReservations = (reservations ?? []).filter(
    (r) => r.guest_id === selectedThread?.guest_id && r.status !== "cancelled",
  );
  const currentRes = guestReservations.find((r) => r.status === "checked_in") ?? guestReservations[0];

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const filteredConversations = (conversations ?? []).filter((c) => {
    if (!threadSearch) return true;
    const q = threadSearch.toLowerCase();
    return (
      c.guest_name?.toLowerCase().includes(q) ||
      c.guest_phone?.includes(q) ||
      c.last_message?.toLowerCase().includes(q)
    );
  });

  function handleSend() {
    if (!reply.trim() || !selectedThread) return;
    sendMessage.mutate({
      to_phone: selectedThread.guest_phone,
      body: reply.trim(),
      guest_id: selectedThread.guest_id,
    });
    setReply("");
  }

  function insertTemplate(body: string) {
    let text = body;
    if (guest) {
      text = text.replace(/\{guest_name\}/g, `${guest.first_name} ${guest.last_name}`);
    }
    if (currentRes?.property_name) {
      text = text.replace(/\{property_name\}/g, currentRes.property_name);
    }
    if (currentRes) {
      text = text.replace(/\{check_in_date\}/g, currentRes.check_in_date);
      text = text.replace(/\{check_out_date\}/g, currentRes.check_out_date);
    }
    setReply(text);
  }

  if (convoLoading) return <ChatSkeleton />;

  const sortedMessages = [...(messages ?? [])].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );
  const datedMessages = sortedMessages.map((msg, index) => {
    const msgDate = new Date(msg.created_at).toLocaleDateString();
    const previousDate =
      index > 0 ? new Date(sortedMessages[index - 1].created_at).toLocaleDateString() : null;
    return {
      ...msg,
      showDate: index === 0 || msgDate !== previousDate,
    };
  });

  return (
    <div className="flex h-[calc(100vh-8rem)] rounded-lg border overflow-hidden">
      {/* Thread list */}
      <div className="w-80 shrink-0 flex flex-col bg-card border-r">
        <div className="p-3 space-y-2">
          <h2 className="font-semibold flex items-center gap-2">
            <MessageSquare className="h-4 w-4" />
            Inbox
            {(conversations ?? []).reduce((s, c) => s + c.unread_count, 0) > 0 && (
              <Badge variant="destructive" className="text-[10px]">
                {conversations!.reduce((s, c) => s + c.unread_count, 0)}
              </Badge>
            )}
          </h2>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search conversations..."
              value={threadSearch}
              onChange={(e) => setThreadSearch(e.target.value)}
              className="pl-8 h-8 text-xs"
            />
          </div>
        </div>
        <Separator />
        <ScrollArea className="flex-1">
          {filteredConversations.map((thread) => (
            <button
              key={thread.guest_phone}
              onClick={() => setSelectedThread(thread)}
              className={cn(
                "w-full text-left p-3 border-b transition-colors hover:bg-accent",
                selectedThread?.guest_phone === thread.guest_phone && "bg-accent",
              )}
            >
              <div className="flex items-start gap-2.5">
                <Avatar className="h-9 w-9 shrink-0 mt-0.5">
                  <AvatarFallback className="text-xs bg-primary/10">
                    {thread.guest_name
                      ?.split(" ")
                      .map((n) => n[0])
                      .join("")
                      .slice(0, 2)
                      .toUpperCase() ?? "?"}
                  </AvatarFallback>
                </Avatar>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium truncate">{thread.guest_name}</p>
                    <span className="text-[10px] text-muted-foreground shrink-0 ml-1">
                      {new Date(thread.last_message_at).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                  {thread.property_name && (
                    <p className="text-[11px] text-muted-foreground truncate">
                      <Home className="inline h-3 w-3 mr-0.5" />
                      {thread.property_name}
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground line-clamp-1 mt-0.5">
                    {thread.last_message}
                  </p>
                </div>
                {thread.unread_count > 0 && (
                  <Badge
                    variant="destructive"
                    className="text-[10px] h-5 min-w-5 rounded-full p-0 flex items-center justify-center shrink-0"
                  >
                    {thread.unread_count}
                  </Badge>
                )}
              </div>
            </button>
          ))}
          {filteredConversations.length === 0 && (
            <div className="p-6 text-center text-sm text-muted-foreground">
              No conversations found
            </div>
          )}
        </ScrollArea>
      </div>

      {/* Chat area */}
      <div className="flex flex-1 flex-col min-w-0">
        {!selectedThread ? (
          <div className="flex flex-1 items-center justify-center text-muted-foreground">
            <div className="text-center">
              <MessageSquare className="h-16 w-16 mx-auto mb-4 opacity-30" />
              <p className="text-lg font-medium">Select a conversation</p>
              <p className="text-sm mt-1">Choose a thread to start messaging</p>
            </div>
          </div>
        ) : (
          <>
            {/* Chat header */}
            <div className="border-b p-3 flex items-center justify-between bg-card">
              <div>
                <p className="font-semibold text-sm">{selectedThread.guest_name}</p>
                <p className="text-xs text-muted-foreground flex items-center gap-2">
                  <Phone className="h-3 w-3" />
                  {selectedThread.guest_phone}
                  {currentRes && (
                    <>
                      <span>·</span>
                      <Home className="h-3 w-3" />
                      {currentRes.property_name ?? ""}
                    </>
                  )}
                </p>
              </div>
              {currentRes && (
                <Badge variant="outline" className="text-xs">
                  {currentRes.check_in_date} → {currentRes.check_out_date}
                </Badge>
              )}
            </div>

            {/* Messages */}
            <ScrollArea className="flex-1 p-4">
              <div className="space-y-3 max-w-3xl mx-auto">
                {datedMessages.map((msg) => {
                  return (
                    <div key={msg.id}>
                      {msg.showDate && (
                        <div className="flex items-center gap-3 my-4">
                          <Separator className="flex-1" />
                          <span className="text-[10px] text-muted-foreground shrink-0">
                            {new Date(msg.created_at).toLocaleDateString("en-US", {
                              weekday: "short",
                              month: "short",
                              day: "numeric",
                            })}
                          </span>
                          <Separator className="flex-1" />
                        </div>
                      )}
                      <div
                        className={cn(
                          "flex gap-2 max-w-[75%]",
                          msg.direction === "outbound" ? "ml-auto flex-row-reverse" : "",
                        )}
                      >
                        <Avatar className="h-7 w-7 shrink-0 mt-1">
                          <AvatarFallback className="text-[10px]">
                            {msg.direction === "inbound" ? (
                              <User className="h-3.5 w-3.5" />
                            ) : msg.is_auto_response ? (
                              <Bot className="h-3.5 w-3.5" />
                            ) : (
                              "LK"
                            )}
                          </AvatarFallback>
                        </Avatar>
                        <div
                          className={cn(
                            "rounded-2xl px-3.5 py-2 text-sm",
                            msg.direction === "outbound"
                              ? "bg-primary text-primary-foreground rounded-br-sm"
                              : "bg-muted rounded-bl-sm",
                          )}
                        >
                          <p className="whitespace-pre-wrap">{msg.body}</p>
                          <div className="mt-1 flex items-center gap-1.5 opacity-60">
                            <span className="text-[10px]">
                              {new Date(msg.created_at).toLocaleTimeString([], {
                                hour: "2-digit",
                                minute: "2-digit",
                              })}
                            </span>
                            {msg.direction === "outbound" && (
                              msg.status === "delivered" ? (
                                <CheckCheck className="h-3 w-3" />
                              ) : (
                                <Check className="h-3 w-3" />
                              )
                            )}
                            {msg.is_auto_response && (
                              <Badge variant="outline" className="text-[8px] h-3.5 border-primary-foreground/30">
                                AI
                              </Badge>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
                <div ref={bottomRef} />
              </div>
            </ScrollArea>

            {/* Reply area */}
            <div className="border-t p-3 bg-card">
              <div className="flex gap-2 items-end max-w-3xl mx-auto">
                {templates && Array.isArray(templates) && templates.length > 0 && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" className="shrink-0" title="Quick templates">
                        <FileText className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start" className="w-64">
                      {((Array.isArray(templates) ? templates : []) as Array<{ id: string; name: string; body: string }>).slice(0, 10).map((t) => (
                        <DropdownMenuItem key={t.id} onClick={() => insertTemplate(t.body)} className="cursor-pointer">
                          <div>
                            <p className="text-sm font-medium">{t.name}</p>
                            <p className="text-xs text-muted-foreground line-clamp-1">{(t.body ?? "").slice(0, 60)}...</p>
                          </div>
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
                <Textarea
                  placeholder="Type a message..."
                  className="resize-none min-h-[40px] max-h-32"
                  rows={1}
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSend();
                    }
                  }}
                />
                <Button
                  size="icon"
                  className="shrink-0"
                  onClick={handleSend}
                  disabled={!reply.trim() || sendMessage.isPending}
                >
                  <Send className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Guest context sidebar */}
      {selectedThread && guest && (
        <div className="w-72 shrink-0 border-l bg-card overflow-y-auto hidden xl:block">
          <div className="p-4 space-y-4">
            <div className="text-center">
              <Avatar className="h-14 w-14 mx-auto mb-2">
                <AvatarFallback className="text-lg">
                  {guest.first_name?.[0]}
                  {guest.last_name?.[0]}
                </AvatarFallback>
              </Avatar>
              <p className="font-semibold">{guest.first_name} {guest.last_name}</p>
              <div className="flex items-center justify-center gap-1 mt-1">
                {guest.total_stays > 2 && (
                  <Badge variant="default" className="text-[10px]">VIP</Badge>
                )}
                <Badge variant="outline" className="text-[10px]">
                  {guest.total_stays} stay{guest.total_stays !== 1 ? "s" : ""}
                </Badge>
              </div>
            </div>

            <Separator />

            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Contact</p>
              <div className="space-y-1.5 text-sm">
                <p className="flex items-center gap-2">
                  <Phone className="h-3.5 w-3.5 text-muted-foreground" />
                  {guest.phone_number}
                </p>
                {guest.email && (
                  <p className="flex items-center gap-2">
                    <Mail className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="truncate">{guest.email}</span>
                  </p>
                )}
              </div>
            </div>

            {currentRes && (
              <>
                <Separator />
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Current Stay</p>
                  <div className="rounded-lg border p-3 space-y-2 text-sm">
                    <div className="flex items-center gap-2">
                      <Home className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      <span className="font-medium truncate">{currentRes.property_name}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <CalendarDays className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      {currentRes.check_in_date} → {currentRes.check_out_date}
                    </div>
                    <div className="flex items-center gap-2">
                      <User className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      {currentRes.num_guests} guest{currentRes.num_guests !== 1 ? "s" : ""}
                    </div>
                    <Badge variant={
                      currentRes.status === "checked_in" ? "default" : "outline"
                    } className="text-xs">
                      {currentRes.status.replace("_", " ")}
                    </Badge>
                  </div>
                </div>
              </>
            )}

            {guest.lifetime_value != null && guest.lifetime_value > 0 && (
              <>
                <Separator />
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Lifetime Value</p>
                  <p className="text-lg font-bold">${guest.lifetime_value.toLocaleString()}</p>
                </div>
              </>
            )}

            {guest.tags && guest.tags.length > 0 && (
              <>
                <Separator />
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Tags</p>
                  <div className="flex flex-wrap gap-1">
                    {guest.tags.map((t) => (
                      <Badge key={t} variant="secondary" className="text-[10px]">{t}</Badge>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
