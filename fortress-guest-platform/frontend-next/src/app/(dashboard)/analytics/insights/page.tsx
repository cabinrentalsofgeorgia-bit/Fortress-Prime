"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Brain,
  Send,
  TrendingUp,
  Wrench,
  Sparkles,
  ArrowLeft,
  AlertTriangle,
  CheckCircle,
  Loader2,
} from "lucide-react";
import Link from "next/link";

interface AiResponse {
  role: "user" | "ai";
  content: string;
  timestamp: Date;
}

export default function AiInsightsPage() {
  const [query, setQuery] = useState("");
  const [chat, setChat] = useState<AiResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecast, setForecast] = useState<string | null>(null);
  const [maintenanceAlerts, setMaintenanceAlerts] = useState<string[] | null>(null);
  const [listingTips, setListingTips] = useState<string | null>(null);

  async function handleAsk(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    const userMsg: AiResponse = { role: "user", content: query.trim(), timestamp: new Date() };
    setChat((prev) => [...prev, userMsg]);
    setQuery("");
    setLoading(true);
    try {
      const res = await api.post<{ response: string }>("/api/ai/ask", { query: userMsg.content });
      setChat((prev) => [...prev, { role: "ai", content: res.response ?? "No response", timestamp: new Date() }]);
    } catch {
      setChat((prev) => [...prev, { role: "ai", content: "AI engine is currently unavailable. Please check that the backend is running.", timestamp: new Date() }]);
    }
    setLoading(false);
  }

  async function loadForecast() {
    setForecastLoading(true);
    try {
      const res = await api.get<{ forecast: string }>("/api/ai/forecast");
      setForecast(res.forecast ?? "Revenue forecast data will appear here when the AI engine processes your historical data.");
    } catch {
      setForecast("Revenue forecasting requires the AI engine to be running. Connect to Ollama to enable this feature.");
    }
    setForecastLoading(false);
  }

  async function loadMaintenance() {
    try {
      const res = await api.get<{ alerts: string[] }>("/api/ai/predict-maintenance");
      setMaintenanceAlerts(res.alerts ?? ["No maintenance predictions available yet."]);
    } catch {
      setMaintenanceAlerts(["Predictive maintenance requires work order history. Continue logging work orders to enable AI predictions."]);
    }
  }

  async function loadListingTips() {
    try {
      const res = await api.get<{ suggestions: string }>("/api/ai/optimize-listing");
      setListingTips(res.suggestions ?? "Listing optimization suggestions will appear here.");
    } catch {
      setListingTips("Listing optimization requires active properties with bookings. This feature analyzes your listing performance to suggest improvements.");
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/analytics">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="mr-2 h-4 w-4" />
            Analytics
          </Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Brain className="h-6 w-6 text-violet-500" />
            AI Insights
          </h1>
          <p className="text-muted-foreground">
            Ask questions, get forecasts, and receive AI-powered recommendations
          </p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Chat panel */}
        <Card className="lg:row-span-2">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-amber-500" />
              Ask Your Data
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col h-[500px]">
            <ScrollArea className="flex-1 mb-4">
              <div className="space-y-3">
                {chat.length === 0 && (
                  <div className="text-center py-8 text-muted-foreground text-sm">
                    <Brain className="h-10 w-10 mx-auto mb-3 opacity-30" />
                    <p>Ask anything about your business</p>
                    <div className="mt-3 space-y-1">
                      <p className="text-xs">"What's my revenue this month?"</p>
                      <p className="text-xs">"Which property has the most cancellations?"</p>
                      <p className="text-xs">"How does February compare to January?"</p>
                    </div>
                  </div>
                )}
                {chat.map((msg, i) => (
                  <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : ""}`}>
                    <div className={`rounded-lg px-3 py-2 text-sm max-w-[85%] ${
                      msg.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"
                    }`}>
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    </div>
                  </div>
                ))}
                {loading && (
                  <div className="flex gap-2 items-center text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Thinking...
                  </div>
                )}
              </div>
            </ScrollArea>
            <form onSubmit={handleAsk} className="flex gap-2">
              <Input
                placeholder="Ask a question..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                disabled={loading}
              />
              <Button size="icon" type="submit" disabled={loading || !query.trim()}>
                <Send className="h-4 w-4" />
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Revenue Forecast */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <TrendingUp className="h-4 w-4 text-green-500" />
                Revenue Forecast
              </CardTitle>
              <Button variant="outline" size="sm" onClick={loadForecast} disabled={forecastLoading}>
                {forecastLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Generate"}
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {forecast ? (
              <p className="text-sm whitespace-pre-wrap">{forecast}</p>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-4">
                Click Generate to create an AI-powered revenue forecast based on your historical data
              </p>
            )}
          </CardContent>
        </Card>

        {/* Predictive Maintenance */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <Wrench className="h-4 w-4 text-orange-500" />
                Predictive Maintenance
              </CardTitle>
              <Button variant="outline" size="sm" onClick={loadMaintenance}>
                Analyze
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {maintenanceAlerts ? (
              <div className="space-y-2">
                {maintenanceAlerts.map((a, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm">
                    <AlertTriangle className="h-4 w-4 text-orange-500 shrink-0 mt-0.5" />
                    <span>{a}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground text-center py-4">
                AI analyzes work order patterns to predict upcoming maintenance needs
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Listing Optimization */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <CheckCircle className="h-5 w-5 text-blue-500" />
              Listing Optimization
            </CardTitle>
            <Button variant="outline" size="sm" onClick={loadListingTips}>
              Get Suggestions
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {listingTips ? (
            <p className="text-sm whitespace-pre-wrap">{listingTips}</p>
          ) : (
            <p className="text-sm text-muted-foreground text-center py-4">
              AI reviews your property listings and suggests improvements to boost bookings and revenue
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
