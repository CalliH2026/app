# School pilot interest

The EN/FR landing has a pilot CTA, an anonymous interactive metropolitan-France map and an interest form. The user confirmed three participating schools in Île-de-France on 8 November 2026. Labels 01–03 and marker positions protect their identities; they do not name random real schools. The displayed participant count is curated, not inferred from leads.

`POST /pilot/interest` saves work email, school, role, language, consent version and creation timestamp in D1 `DB.pilot_interest`. Email is normalized and unique. No email is sent, account created, or native access granted. All school-data writes remain blocked. Controls: same-origin JSON only, 2 KiB body bound, field allowlist/length checks, honeypot, explicit consent, duplicate suppression and a 250/day admission cap. No IP, device identifier or student field is stored. Success requires database acknowledgment; outages return 503.

Contacts are private: the endpoint allows POST only, with no reader. The owner can inspect the `pilot_interest` table through Sites Settings → Database, or its authenticated database tools. Do not publish exports or copy live contacts into Git. Follow-up is manual; the form does not silently subscribe anyone to a newsletter. Retention should be reviewed when the pilot closes.

The public QA registration, if present, is identified by `QA — technical verification, not a school` and an `@example.invalid` address. It is not a participant and must not be included in the three-school count or outreach.

Schema-only migration: `drizzle/0001_pilot_interest.sql`. Tests include real SQLite persistence, duplicate behavior, malformed input, origin/size limits, failures, and unchanged native write restrictions. The local browser test uses an ephemeral SQLite database.

Natural Earth outline: public domain; source in `src/landing/assets/france-pilot-source.md`. No third-party map requests.
