"use client";

import { useActionState, useId } from "react";
import { createTester, reissueInvite } from "@/app/actions";

/** Only the owner page renders this form, and both actions authorize again. */
export function InviteForm({ testerId, email, signupId }: {
  testerId?: string; email?: string; signupId?: string;
}) {
  const [state, action, pending] = useActionState(testerId ? reissueInvite : createTester, {});
  const id = useId();
  return (
    <div>
      <form action={action} className="row" style={{ gap: 8, alignItems: "flex-end", display: state.code ? "none" : undefined }}>
        {testerId ? <input type="hidden" name="id" value={testerId} /> : (
          <>
            <div>
              <label className="label" htmlFor={`${id}-name`}>Name</label>
              <input id={`${id}-name`} name="name" className="field" required maxLength={120} autoComplete="off" />
            </div>
            {email !== undefined ? <input type="hidden" name="email" value={email} /> : (
              <div>
                <label className="label" htmlFor={`${id}-email`}>Email (optional)</label>
                <input id={`${id}-email`} name="email" className="field" type="email" maxLength={320} autoComplete="off" />
              </div>
            )}
            {signupId ? <input type="hidden" name="signup_id" value={signupId} /> : null}
          </>
        )}
        <button className={`btn ${testerId ? "small" : "primary"}`} type="submit" disabled={pending}>
          {pending ? "Creating…" : testerId ? "Issue new code" : "Generate code"}
        </button>
      </form>
      {state.error ? <p className="notice error" role="alert">{state.error}</p> : null}
      {state.code ? (
        <div className="notice" role="status" style={{ marginTop: 10, maxWidth: 440 }}>
          <p>Copy this code for {state.testerName} now. It is shown only here and can be used once.</p>
          <code style={{ display: "block", overflowWrap: "anywhere", userSelect: "all", margin: "8px 0" }}>{state.code}</code>
          <p>Expires {new Date(state.expiresAt!).toLocaleDateString()}. Lost it? Issue a new code.</p>
          <a href="/testers">Done — return to roster</a>
        </div>
      ) : null}
    </div>
  );
}
