"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type Props = {
  onCreateRoutingRule: (payload: {
    rule_type: string;
    pattern: string;
    action: string;
    division?: string;
    reason?: string;
  }) => void;
  onCreateClassificationRule: (payload: {
    division: string;
    match_field: string;
    pattern: string;
    weight: number;
    notes?: string;
  }) => void;
  onCreateEscalationRule: (payload: {
    rule_name: string;
    trigger_type: string;
    match_field: string;
    pattern: string;
    priority: string;
    notes?: string;
  }) => void;
};

export function RulesCreateForms({
  onCreateRoutingRule,
  onCreateClassificationRule,
  onCreateEscalationRule,
}: Props) {
  const [routingRuleType, setRoutingRuleType] = useState("sender_block");
  const [routingPattern, setRoutingPattern] = useState("");
  const [routingAction, setRoutingAction] = useState("REJECT");
  const [routingReason, setRoutingReason] = useState("");

  const [classDivision, setClassDivision] = useState("CABIN_VRS");
  const [classField, setClassField] = useState("sender");
  const [classPattern, setClassPattern] = useState("");
  const [classWeight, setClassWeight] = useState("20");
  const [classNotes, setClassNotes] = useState("");

  const [escName, setEscName] = useState("");
  const [escTrigger, setEscTrigger] = useState("content_flag");
  const [escField, setEscField] = useState("subject");
  const [escPattern, setEscPattern] = useState("");
  const [escPriority, setEscPriority] = useState("P2");

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add Routing Rule</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-5">
          <Select value={routingRuleType} onValueChange={setRoutingRuleType}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="sender_block">sender_block</SelectItem>
              <SelectItem value="subject_block">subject_block</SelectItem>
              <SelectItem value="content_block">content_block</SelectItem>
              <SelectItem value="domain_trust">domain_trust</SelectItem>
              <SelectItem value="sender_vip">sender_vip</SelectItem>
              <SelectItem value="domain_block">domain_block</SelectItem>
            </SelectContent>
          </Select>
          <Input value={routingPattern} onChange={(e) => setRoutingPattern(e.target.value)} placeholder="Pattern" />
          <Select value={routingAction} onValueChange={setRoutingAction}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="REJECT">REJECT</SelectItem>
              <SelectItem value="QUARANTINE">QUARANTINE</SelectItem>
              <SelectItem value="ALLOW">ALLOW</SelectItem>
              <SelectItem value="ESCALATE">ESCALATE</SelectItem>
              <SelectItem value="PRIORITY">PRIORITY</SelectItem>
            </SelectContent>
          </Select>
          <Input value={routingReason} onChange={(e) => setRoutingReason(e.target.value)} placeholder="Reason" />
          <Button
            onClick={() => {
              if (!routingPattern.trim()) return;
              onCreateRoutingRule({
                rule_type: routingRuleType,
                pattern: routingPattern.trim(),
                action: routingAction,
                reason: routingReason.trim(),
              });
              setRoutingPattern("");
              setRoutingReason("");
            }}
          >
            Add Rule
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add Classification Rule</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-6">
          <Input value={classDivision} onChange={(e) => setClassDivision(e.target.value)} placeholder="Division" />
          <Select value={classField} onValueChange={setClassField}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="sender">sender</SelectItem>
              <SelectItem value="subject">subject</SelectItem>
              <SelectItem value="body">body</SelectItem>
              <SelectItem value="any">any</SelectItem>
            </SelectContent>
          </Select>
          <Input value={classPattern} onChange={(e) => setClassPattern(e.target.value)} placeholder="Pattern" />
          <Input value={classWeight} onChange={(e) => setClassWeight(e.target.value)} placeholder="Weight" />
          <Input value={classNotes} onChange={(e) => setClassNotes(e.target.value)} placeholder="Notes" />
          <Button
            onClick={() => {
              if (!classPattern.trim()) return;
              onCreateClassificationRule({
                division: classDivision.trim(),
                match_field: classField,
                pattern: classPattern.trim(),
                weight: Number(classWeight) || 20,
                notes: classNotes.trim(),
              });
              setClassPattern("");
              setClassNotes("");
            }}
          >
            Add Rule
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add Escalation Rule</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-6">
          <Input value={escName} onChange={(e) => setEscName(e.target.value)} placeholder="Rule name" />
          <Select value={escTrigger} onValueChange={setEscTrigger}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="content_flag">content_flag</SelectItem>
              <SelectItem value="vip_sender">vip_sender</SelectItem>
              <SelectItem value="high_value">high_value</SelectItem>
              <SelectItem value="failed_classification">failed_classification</SelectItem>
            </SelectContent>
          </Select>
          <Select value={escField} onValueChange={setEscField}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="subject">subject</SelectItem>
              <SelectItem value="body">body</SelectItem>
              <SelectItem value="sender">sender</SelectItem>
              <SelectItem value="any">any</SelectItem>
            </SelectContent>
          </Select>
          <Input value={escPattern} onChange={(e) => setEscPattern(e.target.value)} placeholder="Pattern" />
          <Select value={escPriority} onValueChange={setEscPriority}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="P0">P0</SelectItem>
              <SelectItem value="P1">P1</SelectItem>
              <SelectItem value="P2">P2</SelectItem>
              <SelectItem value="P3">P3</SelectItem>
            </SelectContent>
          </Select>
          <Button
            onClick={() => {
              if (!escName.trim() || !escPattern.trim()) return;
              onCreateEscalationRule({
                rule_name: escName.trim(),
                trigger_type: escTrigger,
                match_field: escField,
                pattern: escPattern.trim(),
                priority: escPriority,
              });
              setEscName("");
              setEscPattern("");
            }}
          >
            Add Rule
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

