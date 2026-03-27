# Legacy Reservation Form Variants

Source evidence:

- `/mnt/vol1_source/Backups/CPanel_Extracted/backup-1.18.2026_21-12-59_cabinre/mysql/cabinre_drupal7.sql`
- `/mnt/vol1_source/Backups/CPanel_Extracted/cabinre_legacy_migration_cut.sql`

Method:

- Parsed Drupal `cache_form` entries where `#id = crog-reservations-book-form`
- Joined each cached form back to `url_alias`, `node`, and `field_data_field_streamline_id`

High-level findings:

- Total cached reservation form entries recovered: `182`
- Distinct cabins represented in cache: `11`
- Every recovered cabin form preserves `cabin_id == streamline_id`
- Form actions use Drupal node routes such as `/reservations/book/2045`
- Modal variants also exist with query strings such as `?width=390&height=auto&inline=true`
- Discount defaults seen in cached forms: ``, `SAVE10`, `STAY647`, `Save10`, `WINTER243`

## Sample Recovered Form Skeleton

The recovered Drupal form structure consistently contains:

- `#form_id = crog_reservations_book_form`
- `#id = crog-reservations-book-form`
- hidden `nid`
- hidden `cabin_id`
- `startdate`
- `enddate`
- `adults`
- `children`
- `pets`
- `pets_detail`
- `discount`
- optional add-on checkboxes
- `submit = Instant Quote`
- sometimes `pay = Book It`

Representative action bridge:

- `Aska Escape Lodge`
- `nid = 2045`
- `streamline_id = 235641`
- `cabin_id = 235641`
- action `/reservations/book/2045`

## Distinct Cabin Variant Summary

### `cabin/blue-ridge/above-the-timberline`

- `nid`: `2454`
- `streamline_id`: `382651`
- recovered entries: `15`
- `cabin_id` values: `382651`
- actions:
  - `/reservations/book/2454`
  - `/reservations/book/2454?height=auto&inline=true&width=400`
  - `/reservations/book/2454?width=390&height=auto&inline=true`
  - `/reservations/book/2454?width=400&height=auto&inline=true`
- discount defaults: ``, `STAY647`
- option count: `8`
- options:
  - `1 Hour Early Check-In Fee ($50.00)`
  - `1 Hour Late Check-Out Fee ($50.00)`
  - `2 Hour Early Check-In Fee ($100.00)`
  - `2 Hour Late Check-Out Fee ($100.00)`
  - `Firewood 1/2 Face Cord ($165.00)`
  - `Firewood 1/4 Face Cord ($135.00)`
  - `Full Day Guided Private Water Trophy Fishing for 1 Person ($425.00)`
  - `1/2 day Guided Private Water Trophy Fishing for 1 Person ($250.00)`  

### `cabin/blue-ridge/aska-escape-lodge`

- `nid`: `2045`
- `streamline_id`: `235641`
- recovered entries: `70`
- `cabin_id` values: `235641`
- actions:
  - `/reservations/book/2045`
  - `/reservations/book/2045?width=390&height=auto&inline=true`
  - `/reservations/book/2045?width=400&height=auto&inline=true`
- discount defaults: ``, `SAVE10`, `STAY647`, `Save10`, `WINTER243`
- option count: `8`
- options:
  - `1 Hour Early Check-In Fee ($50.00)`
  - `1 Hour Late Check-Out Fee ($50.00)`
  - `2 Hour Early Check-In Fee ($100.00)`
  - `2 Hour Late Check-Out Fee ($100.00)`
  - `Firewood 1/2 Face Cord ($165.00)`
  - `Firewood 1/4 Face Cord ($135.00)`
  - `Full Day Guided Private Water Trophy Fishing for 1 Person ($425.00)`
  - `1/2 day Guided Private Water Trophy Fishing for 1 Person ($250.00)`

### `cabin/blue-ridge/cherokee-sunrise-noontootla-creek`

- `nid`: `2357`
- `streamline_id`: `306758`
- recovered entries: `6`
- `cabin_id` values: `306758`
- actions:
  - `/reservations/book/2357`
  - `/reservations/book/2357?width=390&height=auto&inline=true`
  - `/reservations/book/2357?width=400&height=auto&inline=true`
- discount defaults: ``
- option count: `8`

### `cabin/blue-ridge/cohutta-sunset`

- `nid`: `1359`
- `streamline_id`: `70206`
- recovered entries: `16`
- `cabin_id` values: `70206`
- actions:
  - `/reservations/book/1359`
  - `/reservations/book/1359?width=390&height=auto&inline=true`
  - `/reservations/book/1359?width=400&height=auto&inline=true`
- discount defaults: ``, `STAY647`
- option count: `8`

### `cabin/blue-ridge/fallen-timber-lodge`

- `nid`: `14`
- `streamline_id`: `70209`
- recovered entries: `21`
- `cabin_id` values: `70209`
- actions:
  - `/reservations/book/14`
  - `/reservations/book/14?width=390&height=auto&inline=true`
  - `/reservations/book/14?width=400&height=auto&inline=true`
- discount defaults: ``
- option count: `8`

### `cabin/blue-ridge/high-hopes`

- `nid`: `2617`
- `streamline_id`: `441334`
- recovered entries: `11`
- `cabin_id` values: `441334`
- actions:
  - `/reservations/book/2617`
  - `/reservations/book/2617?height=auto&inline=true&width=400`
  - `/reservations/book/2617?width=390&height=auto&inline=true`
  - `/reservations/book/2617?width=400&height=auto&inline=true`
- discount defaults: ``, `SAVE10`
- option count: `7`

### `cabin/blue-ridge/riverview-lodge`

- `nid`: `20`
- `streamline_id`: `70220`
- recovered entries: `10`
- `cabin_id` values: `70220`
- actions:
  - `/reservations/book/20`
  - `/reservations/book/20?height=auto&inline=true&width=390`
  - `/reservations/book/20?width=390&height=auto&inline=true`
  - `/reservations/book/20?width=400&height=auto&inline=true`
- discount defaults: ``
- option count: `6`

### `cabin/blue-ridge/serendipity-noontootla-creek`

- `nid`: `25`
- `streamline_id`: `70222`
- recovered entries: `7`
- `cabin_id` values: `70222`
- actions:
  - `/reservations/book/25`
  - `/reservations/book/25?width=390&height=auto&inline=true`
  - `/reservations/book/25?width=400&height=auto&inline=true`
- discount defaults: ``
- option count: `8`

### `cabin/blue-ridge/the-rivers-edge`

- `nid`: `2624`
- `streamline_id`: `70224`
- recovered entries: `8`
- `cabin_id` values: `70224`
- actions:
  - `/reservations/book/2624`
  - `/reservations/book/2624?width=390&height=auto&inline=true`
  - `/reservations/book/2624?width=400&height=auto&inline=true`
- discount defaults: ``
- option count: `7`

### `cabin/chase-mountain-dreams`

- `nid`: `3200`
- `streamline_id`: `980130`
- recovered entries: `6`
- `cabin_id` values: `980130`
- actions:
  - `/reservations/book/3200`
  - `/reservations/book/3200?width=390&height=auto&inline=true`
  - `/reservations/book/3200?width=400&height=auto&inline=true`
- discount defaults: ``
- option count: `6`

### `cabin/cherry-log/creekside-green`

- `nid`: `2936`
- `streamline_id`: `756771`
- recovered entries: `12`
- `cabin_id` values: `756771`
- actions:
  - `/reservations/book/2936`
  - `/reservations/book/2936?width=390&height=auto&inline=true`
  - `/reservations/book/2936?width=400&height=auto&inline=true`
- discount defaults: ``
- option count: `6`

## Interpretation

- The legacy booking bridge is not keyed by `extLID` or `RoomID` in the recovered dumps.
- The stable bridge actually recovered is:
  - Drupal alias -> Drupal `nid`
  - Drupal `nid` -> `field_streamline_id_value`
  - cached booking form hidden `cabin_id` -> same `field_streamline_id_value`
- The cached form confirms that later implementation can safely derive:
  - post target from `nid`
  - booking-system key from `streamline_id`
  - per-cabin option bundles from the cached form variant set

## Caveats

- These forms were recovered from Drupal `cache_form`, not from a live theme template.
- Some entries are modal/lightbox variants rather than full-page variants.
- Serialized text included legacy encoding noise in one option label; it has been normalized above to `1/2 day Guided Private Water Trophy Fishing for 1 Person ($250.00)`.
