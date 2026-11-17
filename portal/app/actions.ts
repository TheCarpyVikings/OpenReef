"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { requireOwner } from "@/lib/auth";
import { hashToken, newInviteCode } from "@/lib/api";
import { serviceClient, sessionClient } from "@/lib/supabase";
import { CLOSED_STATUSES, STATUSES, TESTER_STATUSES, type InviteState, type Status, type TesterStatus } from "@/lib/types";

/*
 * Every mutation in the portal.
 *
 * All of them call requireOwner() first. That is redundant with the middleware
 * gate by design — server actions are POST endpoints with guessable ids, and a
 * matcher typo in middleware.ts should not be the only thing standing between
 * a stranger and this table.
 */

function text(form: FormData, key: string, max: number): string {
  const value = form.get(key);
  return typeof value === "string" ? value.trim().slice(0, max) : "";
}

export async function signOut() {
  const supabase = await sessionClient();
  await supabase.auth.signOut();
  redirect("/login");
}

/* --- feedback triage ------------------------------------------------------ */

/**
 * Move an item's status, optionally attaching the reply the tester will see.
 *
 * The reply and the status change are one write, so the two can never disagree
 * — no "marked actioned but the reply insert failed" state to reconcile. The
 * tester's install picks both up on its next sync and raises a notification.
 */
export async function setStatus(form: FormData) {
  await requireOwner();
  const id = text(form, "id", 64);
  const next = text(form, "status", 32) as Status;
  const reply = text(form, "reply", 2000);
  if (!id || !STATUSES.includes(next)) return;

  const supabase = serviceClient();
  const patch: Record<string, unknown> = { status: next };

  if (reply) {
    patch.reply = reply;
    patch.replied_at = new Date().toISOString();
  }

  // Duplicates need a target; resolve the typed ref to an id and refuse the
  // move rather than letting the DB trigger reject it with a raw error.
  if (next === "duplicate") {
    const ref = text(form, "duplicate_of", 32).toUpperCase();
    if (!ref) return;
    const { data } = await supabase
      .from("beta_feedback")
      .select("id")
      .eq("ref", ref)
      .maybeSingle();
    if (!data || data.id === id) return;
    patch.duplicate_of = data.id;
  } else {
    patch.duplicate_of = null;
  }

  const { error } = await supabase.from("beta_feedback").update(patch).eq("id", id);
  if (error) return;

  await supabase.from("beta_feedback_events").insert({
    feedback_id: id,
    event: CLOSED_STATUSES.includes(next) ? "closed" : "status",
    detail: reply ? `${next}: ${reply.slice(0, 200)}` : next,
  });

  revalidatePath("/");
  revalidatePath(`/feedback/${id}`);
}

/** The private scratchpad. Never leaves the portal — /api/sync doesn't select it. */
export async function saveOwnerNote(form: FormData) {
  await requireOwner();
  const id = text(form, "id", 64);
  if (!id) return;
  await serviceClient()
    .from("beta_feedback")
    .update({ owner_note: text(form, "owner_note", 4000) || null })
    .eq("id", id);
  revalidatePath(`/feedback/${id}`);
}

/* --- testers -------------------------------------------------------------- */

/** Returned once to the owner's action response, never saved as plaintext or
 * placed in a URL/cookie. Seven days gives the tester time to install HA. */
async function invitation() {
  const code = newInviteCode();
  const expiresAt = new Date(Date.now() + 7 * 86_400_000).toISOString();
  return { code, expiresAt, hash: await hashToken(code) };
}

export async function createTester(_previous: InviteState, form: FormData): Promise<InviteState> {
  await requireOwner();
  const name = text(form, "name", 120);
  if (!name) return { error: "Enter the tester's name." };
  const email = text(form, "email", 320).toLowerCase();
  const supabase = serviceClient();
  const invite = await invitation();
  const { data, error } = await supabase.from("beta_testers").insert({
    name, email: email || null, invite_hash: invite.hash, invite_expires_at: invite.expiresAt,
  }).select("id").single();
  if (error || !data) return { error: "Could not create the invitation. Check the portal database migration and try again." };

  // If they came from the waiting list, link the signup so the funnel stays
  // legible: how many asked, how many were invited, how many actually enrolled.
  const signupId = text(form, "signup_id", 64);
  if (signupId && email) {
    await supabase.from("beta_signups").update({ tester_id: data.id }).eq("id", signupId).eq("email", email);
  }

  // Keep the form mounted until the owner has copied its one-time result.
  // Revalidating here would remove a promoted waiting-list row and its code.
  return { code: invite.code, expiresAt: invite.expiresAt, testerName: name };
}

/** Fresh recovery invitation. The current install keeps its token until the
 * new invitation is redeemed; issuing one never resumes a paused account. */
export async function reissueInvite(_previous: InviteState, form: FormData): Promise<InviteState> {
  await requireOwner();
  const id = text(form, "id", 64);
  if (!id) return { error: "Choose a tester." };
  const invite = await invitation();
  const { data, error } = await serviceClient().from("beta_testers")
    .update({ invite_hash: invite.hash, invite_expires_at: invite.expiresAt })
    .eq("id", id).in("status", ["invited", "active"])
    .select("name").maybeSingle();
  if (error || !data) return { error: "Could not issue a code. Resume or restore the tester first, then try again." };
  return { code: invite.code, expiresAt: invite.expiresAt, testerName: data.name };
}

/**
 * Pause, revoke, or reactivate a tester.
 *
 * Revoking clears token_hash as well as setting the status, so the install
 * stops being able to talk to the portal on its very next request. Leaving a
 * live token on a revoked row would make revocation a label rather than an act.
 */
export async function setTesterStatus(form: FormData) {
  await requireOwner();
  const id = text(form, "id", 64);
  const next = text(form, "status", 32) as TesterStatus;
  if (!id || !TESTER_STATUSES.includes(next)) return;

  await serviceClient()
    .from("beta_testers")
    .update({
      status: next,
      ...(next === "paused" || next === "revoked" ? { invite_hash: null, invite_expires_at: null } : {}),
      ...(next === "revoked" ? { token_hash: null } : {}),
    })
    .eq("id", id);
  revalidatePath("/testers");
}

export async function saveTesterNotes(form: FormData) {
  await requireOwner();
  const id = text(form, "id", 64);
  if (!id) return;
  await serviceClient()
    .from("beta_testers")
    .update({ notes: text(form, "notes", 4000) || null })
    .eq("id", id);
  revalidatePath("/testers");
}

/* --- announcements -------------------------------------------------------- */

export async function createAnnouncement(form: FormData) {
  await requireOwner();
  const title = text(form, "title", 200);
  const body = text(form, "body", 2000);
  if (!title || !body) return;
  // Created as a draft. Publishing is a separate, deliberate act — this goes
  // to every active tester at once and there is no unsend.
  await serviceClient().from("beta_announcements").insert({ title, body });
  revalidatePath("/announcements");
}

export async function publishAnnouncement(form: FormData) {
  await requireOwner();
  const id = text(form, "id", 64);
  if (!id) return;
  await serviceClient()
    .from("beta_announcements")
    .update({ published_at: new Date().toISOString() })
    .eq("id", id);
  revalidatePath("/announcements");
}

export async function deleteAnnouncement(form: FormData) {
  await requireOwner();
  const id = text(form, "id", 64);
  if (!id) return;
  await serviceClient().from("beta_announcements").delete().eq("id", id);
  revalidatePath("/announcements");
}
