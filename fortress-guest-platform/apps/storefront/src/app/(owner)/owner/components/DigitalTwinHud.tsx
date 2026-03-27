"use client";

import { usePropertyIoT } from "@/lib/hooks";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Wifi,
  WifiOff,
  Lock,
  LockOpen,
  Thermometer,
  Droplets,
  Video,
  BatteryLow,
  BatteryMedium,
  BatteryFull,
  Activity,
  Loader2,
  AlertTriangle,
} from "lucide-react";

interface ThermostatData {
  device_name: string;
  current_temp: number | null;
  target_temp: number | null;
  mode: string;
  hvac_state: string;
  humidity: number | null;
  is_online: boolean;
}

interface LockData {
  device_name: string;
  lock_state: string;
  battery: number | null;
  is_online: boolean;
  last_user?: string;
}

interface SensorData {
  device_name: string;
  sensor_type: string;
  status: string;
  is_online: boolean;
}

interface CameraData {
  device_name: string;
  status: string;
  is_online: boolean;
}

interface DeviceEvent {
  device_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string | null;
}

interface IoTData {
  property_id: string;
  total_devices: number;
  online_count: number;
  critical_battery: number;
  thermostat: ThermostatData | null;
  locks: LockData[];
  sensors: SensorData[];
  cameras: CameraData[];
  recent_events: DeviceEvent[];
  simulated: boolean;
}

function BatteryIcon({ level }: { level: number | null }) {
  if (level == null) return <BatteryMedium className="h-3 w-3" />;
  if (level < 20) return <BatteryLow className="h-3 w-3 text-red-500" />;
  if (level < 50) return <BatteryMedium className="h-3 w-3 text-amber-500" />;
  return <BatteryFull className="h-3 w-3 text-emerald-500" />;
}

function OnlineIndicator({ online }: { online: boolean }) {
  return online ? (
    <Wifi className="h-3.5 w-3.5 text-emerald-500" />
  ) : (
    <WifiOff className="h-3.5 w-3.5 text-red-500" />
  );
}

export function DigitalTwinHud({ propertyId }: { propertyId: string }) {
  const { data, isLoading } = usePropertyIoT(propertyId);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <Loader2 className="h-5 w-5 mr-2 animate-spin" />
        Connecting to cabin telemetry...
      </div>
    );
  }

  const iot = data as IoTData | undefined;
  if (!iot) return null;

  return (
    <div className="space-y-6">
      {/* Summary strip */}
      <div className="grid gap-3 md:grid-cols-4">
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">Total Devices</p>
            <p className="text-2xl font-bold font-mono">{iot.total_devices}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">Online</p>
            <p className="text-2xl font-bold font-mono text-emerald-500">
              {iot.online_count}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">Critical Battery</p>
            <p
              className={`text-2xl font-bold font-mono ${iot.critical_battery > 0 ? "text-red-500" : "text-muted-foreground"}`}
            >
              {iot.critical_battery}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 pb-3">
            <p className="text-xs text-muted-foreground">Data Source</p>
            <Badge variant={iot.simulated ? "secondary" : "default"}>
              {iot.simulated ? "Simulated" : "Live Telemetry"}
            </Badge>
          </CardContent>
        </Card>
      </div>

      {iot.simulated && (
        <div className="flex items-center gap-2 text-xs text-amber-500 border border-amber-500/30 rounded-md p-2 bg-amber-500/5">
          <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
          Physical bridge not connected for this property. Showing simulated
          telemetry. Connect the Z-Wave hub to enable live data.
        </div>
      )}

      {/* Device grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Thermostat */}
        {iot.thermostat && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <Thermometer className="h-4 w-4 text-blue-400" />
                  {iot.thermostat.device_name}
                </span>
                <OnlineIndicator online={iot.thermostat.is_online} />
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-baseline gap-1">
                <span className="text-4xl font-light font-mono">
                  {iot.thermostat.current_temp ?? "--"}
                </span>
                <span className="text-lg text-muted-foreground">°F</span>
              </div>
              <div className="flex gap-3 mt-2 text-xs text-muted-foreground">
                <span>Target: {iot.thermostat.target_temp ?? "--"}°F</span>
                {iot.thermostat.humidity != null && (
                  <span>{iot.thermostat.humidity}% Humidity</span>
                )}
              </div>
              <div className="flex gap-2 mt-2">
                <Badge variant="outline" className="text-xs capitalize">
                  {iot.thermostat.mode}
                </Badge>
                <Badge
                  variant={
                    iot.thermostat.hvac_state === "idle"
                      ? "secondary"
                      : "default"
                  }
                  className="text-xs capitalize"
                >
                  {iot.thermostat.hvac_state}
                </Badge>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Locks */}
        {iot.locks.map((lock, idx) => {
          const isLocked =
            lock.lock_state === "LOCKED" || lock.lock_state === "locked";
          return (
            <Card key={`lock-${idx}`}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    {isLocked ? (
                      <Lock className="h-4 w-4 text-emerald-500" />
                    ) : (
                      <LockOpen className="h-4 w-4 text-amber-500" />
                    )}
                    {lock.device_name}
                  </span>
                  <OnlineIndicator online={lock.is_online} />
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p
                  className={`text-xl font-medium uppercase ${isLocked ? "text-emerald-500" : "text-amber-500"}`}
                >
                  {lock.lock_state}
                </p>
                <div className="flex items-center gap-1 mt-2 text-xs text-muted-foreground">
                  <BatteryIcon level={lock.battery} />
                  <span>{lock.battery ?? "--"}%</span>
                  {lock.last_user && (
                    <span className="ml-2">Last: {lock.last_user}</span>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}

        {/* Sensors */}
        {iot.sensors.map((sensor, idx) => {
          const isDry =
            sensor.status === "dry" || sensor.status === "nominal";
          return (
            <Card key={`sensor-${idx}`}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <Droplets
                      className={`h-4 w-4 ${isDry ? "text-emerald-500" : "text-red-500"}`}
                    />
                    {sensor.device_name}
                  </span>
                  <OnlineIndicator online={sensor.is_online} />
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p
                  className={`text-xl font-medium capitalize ${isDry ? "" : "text-red-500 animate-pulse"}`}
                >
                  {sensor.status}
                </p>
                <p className="text-xs text-muted-foreground mt-1 capitalize">
                  {sensor.sensor_type.replace("_", " ")}
                </p>
              </CardContent>
            </Card>
          );
        })}

        {/* Cameras */}
        {iot.cameras.map((cam, idx) => (
          <Card key={`cam-${idx}`}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <Video className="h-4 w-4 text-blue-400" />
                  {cam.device_name}
                </span>
                <OnlineIndicator online={cam.is_online} />
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xl font-medium capitalize">{cam.status}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Recent events */}
      {iot.recent_events.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-1.5">
              <Activity className="h-4 w-4" />
              Recent Events
            </CardTitle>
            <CardDescription>Last 20 device state changes</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 max-h-60 overflow-y-auto">
              {iot.recent_events.map((evt, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between text-xs border-b border-border/50 pb-1.5"
                >
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-[10px] font-mono">
                      {evt.device_id}
                    </Badge>
                    <span className="text-muted-foreground">
                      {evt.event_type}
                    </span>
                  </div>
                  <span className="text-muted-foreground font-mono">
                    {evt.created_at
                      ? new Date(evt.created_at).toLocaleString()
                      : "—"}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
