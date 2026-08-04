/*
 * The version of the beta agreement + privacy notice a tester accepts at
 * enrolment. Stamped into beta_testers.agreement_version so "who agreed to
 * what" survives future rewording.
 *
 * KEEP IN LOCKSTEP with the `Version:` line at the top of
 * content/beta-agreement.md and content/privacy-notice.md — bump all three
 * together when the wording changes materially. (Deliberately a dumb constant
 * rather than parsed out of the markdown: parsing would make a formatting edit
 * able to silently change what enrolments record.)
 */
export const AGREEMENT_VERSION = "2026-08-04";
