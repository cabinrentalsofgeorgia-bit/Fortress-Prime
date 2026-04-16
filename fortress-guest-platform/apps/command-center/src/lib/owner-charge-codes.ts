/**
 * Owner charge transaction type codes — mirrors backend OwnerChargeType enum.
 * Source of truth: backend/models/owner_charge.py OwnerChargeType
 * Last sync: I.1 (2026-04-16) — 21 values matching Streamline parity.
 *
 * Ordering: Streamline's canonical order with "(Select)" placeholder first.
 * Never mutate this list without a corresponding Alembic migration.
 */

export interface OwnerChargeCode {
  /** Enum value sent to the backend (snake_case). */
  value: string;
  /** Human-readable label shown in the UI and on PDFs. */
  label: string;
}

/** Placeholder entry for the unset state in the form dropdown. */
export const CHARGE_CODE_PLACEHOLDER = "(Select Transaction Code)";

/** All 21 valid transaction codes in Streamline canonical order. */
export const OWNER_CHARGE_CODES: OwnerChargeCode[] = [
  { value: "third_party_ota_commission",  label: "3rd Party OTA Commission" },
  { value: "advertising_fee",             label: "Advertising Fee" },
  { value: "cleaning_fee",                label: "Cleaning Fee" },
  { value: "credit_from_management",      label: "Credit From Management" },
  { value: "statement_marker",            label: "Statement Marker" },
  { value: "room_revenue",                label: "Room Revenue" },
  { value: "management_fee",              label: "Management Fee" },
  { value: "electric_bill",               label: "Electric Bill" },
  { value: "hacienda_tax",                label: "Hacienda Tax" },
  { value: "linen",                       label: "Linen" },
  { value: "maintenance",                 label: "Maintenance" },
  { value: "adjust_owner_revenue",        label: "Adjust Owner Revenue" },
  { value: "travel_agent_fee",            label: "Travel Agent Fee" },
  { value: "charge_expired_owner",        label: "Charge Expired Owner" },
  { value: "credit_card_dispute",         label: "Credit Card Dispute" },
  { value: "federal_tax_withholding",     label: "Federal Tax Withholding" },
  { value: "housekeeper_pay",             label: "Housekeeper Pay" },
  { value: "landscaping",                 label: "Landscaping" },
  { value: "misc_guest_charges",          label: "Miscellaneous Guest Charges" },
  { value: "pay_to_old_owner",            label: "Pay To Old Owner" },
  { value: "supplies",                    label: "Supplies" },
];

/** Look up display label for a raw enum value (e.g. from API response). */
export function chargeCodeLabel(value: string): string {
  return OWNER_CHARGE_CODES.find((c) => c.value === value)?.label ?? value;
}
