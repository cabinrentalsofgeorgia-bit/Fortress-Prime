"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useFormStatus } from "react-dom";
import { Loader2, ShieldPlus } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  provisionStaffAccount,
  type ProvisionStaffActionState,
} from "./actions";

const INITIAL_STATE: ProvisionStaffActionState = { status: "idle" };

function SubmitButton() {
  const { pending } = useFormStatus();

  return (
    <Button
      type="submit"
      disabled={pending}
      className="bg-emerald-600 text-white hover:bg-emerald-500"
    >
      {pending ? (
        <>
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Cutting Keys...
        </>
      ) : (
        "Provision Account"
      )}
    </Button>
  );
}

export function ProvisionAccountForm() {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<"manager" | "reviewer">("manager");
  const [state, formAction] = useActionState(provisionStaffAccount, INITIAL_STATE);

  useEffect(() => {
    if (state.status === "success") {
      toast.success(state.message);
      formRef.current?.reset();
      router.refresh();
      requestAnimationFrame(() => {
        setOpen(false);
        setRole("manager");
      });
      return;
    }

    if (state.status === "error") {
      toast.error(state.message);
    }
  }, [router, state]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="bg-emerald-600 text-white hover:bg-emerald-500">
          <ShieldPlus className="mr-2 h-4 w-4" />
          Provision Account
        </Button>
      </DialogTrigger>
      <DialogContent className="border-zinc-800 bg-zinc-950 text-zinc-100">
        <DialogHeader>
          <DialogTitle>Provision Scoped Keys</DialogTitle>
          <DialogDescription className="text-zinc-400">
            Create a new manager or reviewer account directly from the Command Center.
          </DialogDescription>
        </DialogHeader>
        <form ref={formRef} action={formAction} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="staff-email">Staff Email</Label>
            <Input
              id="staff-email"
              name="email"
              type="email"
              required
              placeholder="ops@crog-ai.com"
              className="border-zinc-800 bg-zinc-900"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="staff-password">Initial Password</Label>
            <Input
              id="staff-password"
              name="password"
              type="password"
              required
              minLength={8}
              placeholder="Minimum 8 characters"
              className="border-zinc-800 bg-zinc-900"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="staff-role">Role</Label>
            <input type="hidden" name="role" value={role} />
            <Select value={role} onValueChange={(value: "manager" | "reviewer") => setRole(value)}>
              <SelectTrigger id="staff-role" className="border-zinc-800 bg-zinc-900">
                <SelectValue placeholder="Select role" />
              </SelectTrigger>
              <SelectContent className="border-zinc-800 bg-zinc-950 text-zinc-100">
                <SelectItem value="manager">Manager</SelectItem>
                <SelectItem value="reviewer">Reviewer</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {state.status === "error" ? (
            <p className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
              {state.message}
            </p>
          ) : null}
          <DialogFooter className="gap-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <SubmitButton />
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
