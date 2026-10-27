# Portal migration needed for `client-email` (t_d2f75685, item 7)

The engine now accepts `--verify-type client-email` on a `needs-human` transition. It upserts a `citation_verification` row with
`verification_type = 'client-email'`. The portal table (the portal repo, migration `20261026000001_citation_verification_client_actions.sql`) has

```sql
check (verification_type in ('phone-call', 'sms', 'postcard', 'id-check'))
```

so until the check is widened, the portal write for a client-email row is refused by the database. The queue write still stands (the transition code
never lets a portal error block the queue file), and the error shows in `errors` of the transition result (exit 2).

**Order: apply to prod BEFORE the first client-email row is written; this repo's PR does not need it to merge.** It is a portal-repo change, so
this seat does not make it (card constraint: never work in the portal repo). Draft, additive and idempotent, for Nate / Mike to packet:

```sql
alter table citation_verification drop constraint if exists citation_verification_verification_type_check;
alter table citation_verification
  add constraint citation_verification_verification_type_check
  check (verification_type in ('phone-call', 'sms', 'postcard', 'id-check', 'client-email'));
```

The portal "Your turn" page also needs a card for `client-email` (plain text: "<Directory> needs an email address that belongs to your business.
Reply with the address you want on the listing."). Until then the row reads as a generic client gate. Rule behind it (Nate, 2026-10-27): we never attest
that listings@ "belongs directly to the business and is not a proxy or agency-controlled address"; we control listings@, so the attestation would be false.
