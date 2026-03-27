"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Lock,
  LockOpen,
  Zap,
  WifiOff,
  Thermometer,
  Radio,
} from "lucide-react";

interface DigitalTwin {
  device_id: string;
  property_id: string;
  device_type: string;
  device_name: string | null;
  state_json: Record<string, unknown>;
  battery_level: number;
  is_online: boolean;
  last_event_ts: string;
  updated_at: string;
}

export function DigitalTwinGrid() {
  const [twins, setTwins] = useState<DigitalTwin[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchTwins = async () => {
    try {
      const data = await api.get<DigitalTwin[]>("/api/iot/twins");
      if (Array.isArray(data)) {
        setTwins(data);
      }
    } catch (error) {
      console.error("Failed to fetch Digital Twins:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTwins();
    const interval = setInterval(fetchTwins, 10_000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {[1, 2, 3].map((i) => (
          <Card key={i}>
            <CardContent className="p-6">
              <Skeleton className="h-32 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  const onlineCount = twins.filter((t) => t.is_online).length;
  const criticalBatteryCount = twins.filter(
    (t) => t.battery_level <= 15,
  ).length;

  return (
    <div className="space-y-6">
      {/* KPI Strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Total Devices
            </CardTitle>
            <Radio className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{twins.length}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Network Status
            </CardTitle>
            <WifiOff
              className={`h-4 w-4 ${twins.length !== onlineCount ? "text-red-500" : "text-muted-foreground"}`}
            />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {onlineCount} / {twins.length}
            </div>
            <p className="text-xs text-muted-foreground">Online</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Critical Battery
            </CardTitle>
            <Zap
              className={`h-4 w-4 ${criticalBatteryCount > 0 ? "text-amber-500" : "text-muted-foreground"}`}
            />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{criticalBatteryCount}</div>
            <p className="text-xs text-muted-foreground">
              Devices &lt;= 15%
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Device Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {twins.map((twin) => {
          const isLocked = twin.state_json?.lock_state === "locked";
          const batteryCritical = twin.battery_level <= 15;

          return (
            <Card key={twin.device_id}>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-base font-bold truncate pr-2">
                  {twin.device_name ?? twin.device_id}
                </CardTitle>
                {!twin.is_online ? (
                  <Badge
                    variant="destructive"
                    className="font-mono text-xs"
                  >
                    <WifiOff className="w-3 h-3 mr-1" /> OFFLINE
                  </Badge>
                ) : (
                  <Badge
                    variant="default"
                    className="bg-emerald-500/10 text-emerald-500 font-mono text-xs border-emerald-500/20"
                  >
                    LIVE
                  </Badge>
                )}
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Lock Status */}
                {twin.device_type === "smart_lock" && (
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-sm text-muted-foreground">
                      Access
                    </span>
                    <div
                      className={`flex items-center text-sm font-semibold ${isLocked ? "text-emerald-500" : "text-amber-500"}`}
                    >
                      {isLocked ? (
                        <Lock className="w-4 h-4 mr-2" />
                      ) : (
                        <LockOpen className="w-4 h-4 mr-2" />
                      )}
                      {isLocked ? "SECURE" : "UNLOCKED"}
                    </div>
                  </div>
                )}

                {/* Thermostat Status */}
                {twin.device_type === "thermostat" && (
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-sm text-muted-foreground">
                      Climate
                    </span>
                    <div className="flex items-center text-sm font-semibold text-blue-400">
                      <Thermometer className="w-4 h-4 mr-2" />
                      {(twin.state_json?.temperature as number) ?? "--"}°
                    </div>
                  </div>
                )}

                {/* Battery */}
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">Power</span>
                  <div
                    className={`flex items-center text-sm font-mono ${batteryCritical ? "text-red-500 animate-pulse" : ""}`}
                  >
                    <Zap className="w-4 h-4 mr-1" />
                    {twin.battery_level}%
                  </div>
                </div>

                <div className="text-[10px] text-muted-foreground font-mono pt-2 border-t border-border">
                  SYNC:{" "}
                  {twin.last_event_ts
                    ? new Date(twin.last_event_ts).toLocaleTimeString()
                    : "—"}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
