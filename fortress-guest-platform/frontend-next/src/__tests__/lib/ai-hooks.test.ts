import { describe, expect, it } from "vitest";

import {
  DEFAULT_AI_INSIGHTS_FORECAST_REQUEST,
  DEFAULT_AI_INSIGHTS_LISTING_REQUEST,
  DEFAULT_AI_INSIGHTS_MAINTENANCE_REQUEST,
  buildAiForecastRequest,
  buildAiListingRequest,
  buildAiMaintenanceRequest,
} from "@/lib/ai-hooks";
import type { ConversationThread, Property, Reservation, WorkOrder } from "@/lib/types";

describe("ai-hooks builders", () => {
  it("builds a richer forecast request from reservations", () => {
    const reservations: Reservation[] = [
      {
        id: "r1",
        confirmation_code: "R1",
        guest_id: "g1",
        property_id: "p1",
        check_in_date: "2026-01-05",
        check_out_date: "2026-01-08",
        num_guests: 4,
        status: "confirmed",
        total_amount: 1200,
        pre_arrival_sent: false,
        access_info_sent: false,
        digital_guide_sent: false,
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "r2",
        confirmation_code: "R2",
        guest_id: "g2",
        property_id: "p1",
        check_in_date: "2026-01-15",
        check_out_date: "2026-01-17",
        num_guests: 2,
        status: "confirmed",
        total_amount: 800,
        pre_arrival_sent: false,
        access_info_sent: false,
        digital_guide_sent: false,
        created_at: "2026-01-10T00:00:00Z",
      },
      {
        id: "r3",
        confirmation_code: "R3",
        guest_id: "g3",
        property_id: "p2",
        check_in_date: "2026-02-01",
        check_out_date: "2026-02-05",
        num_guests: 6,
        status: "cancelled",
        total_amount: 4000,
        pre_arrival_sent: false,
        access_info_sent: false,
        digital_guide_sent: false,
        created_at: "2026-01-28T00:00:00Z",
      },
    ];

    expect(buildAiForecastRequest(reservations)).toEqual({
      historical_data: [
        {
          month: "2026-01",
          revenue: 2000,
          reservation_count: 2,
          occupied_nights: 5,
          guest_count: 6,
          average_booking_value: 1000,
          average_length_of_stay: 2.5,
          average_party_size: 3,
        },
      ],
      forecast_months: 3,
    });
  });

  it("falls back when no reservations are available", () => {
    expect(buildAiForecastRequest([])).toEqual(DEFAULT_AI_INSIGHTS_FORECAST_REQUEST);
  });

  it("builds maintenance summaries and extracts issue keywords", () => {
    const workOrders: WorkOrder[] = [
      {
        id: "wo-1",
        ticket_number: "WO-1",
        property_id: "p1",
        title: "HVAC inspection",
        description: "Guest reported the upstairs heat is weak.",
        category: "hvac",
        priority: "urgent",
        status: "open",
        created_at: "2026-03-01T00:00:00Z",
      },
    ];
    const conversations: ConversationThread[] = [
      {
        guest_id: "g1",
        guest_name: "Ada Lovelace",
        guest_phone: "555-0001",
        last_message: "The wifi and heat are both spotty tonight.",
        last_message_at: "2026-03-02T00:00:00Z",
        unread_count: 1,
        property_name: "Ridgeline Cabin",
      },
      {
        guest_id: "g2",
        guest_name: "Grace Hopper",
        guest_phone: "555-0002",
        last_message: "Thanks again for the stay.",
        last_message_at: "2026-03-03T00:00:00Z",
        unread_count: 0,
        property_name: "Ridgeline Cabin",
      },
    ];

    expect(buildAiMaintenanceRequest(workOrders, conversations)).toEqual({
      work_orders: [
        {
          kind: "summary",
          total_work_orders: 1,
          open_work_orders: 1,
          urgent_work_orders: 1,
          category_breakdown: { hvac: 1 },
          priority_breakdown: { urgent: 1 },
        },
        {
          id: "wo-1",
          ticket_number: "WO-1",
          property_id: "p1",
          property_name: undefined,
          title: "HVAC inspection",
          description: "Guest reported the upstairs heat is weak.",
          category: "hvac",
          priority: "urgent",
          status: "open",
          created_at: "2026-03-01T00:00:00Z",
          issue_keywords: ["hvac", "heat"],
        },
      ],
      messages: [
        {
          kind: "summary",
          total_threads_reviewed: 2,
          maintenance_signal_threads: 1,
        },
        {
          guest_id: "g1",
          guest_name: "Ada Lovelace",
          guest_phone: "555-0001",
          property_name: "Ridgeline Cabin",
          last_message: "The wifi and heat are both spotty tonight.",
          last_message_at: "2026-03-02T00:00:00Z",
          unread_count: 1,
          issue_keywords: ["heat", "wifi"],
        },
      ],
    });
  });

  it("falls back when no maintenance signals are available", () => {
    expect(buildAiMaintenanceRequest([], [])).toEqual(DEFAULT_AI_INSIGHTS_MAINTENANCE_REQUEST);
  });

  it("builds a listing request from the strongest active property", () => {
    const properties: Property[] = [
      {
        id: "p1",
        name: "Small Cabin",
        slug: "small-cabin",
        property_type: "cabin",
        bedrooms: 2,
        bathrooms: 1,
        max_guests: 4,
        is_active: true,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
      {
        id: "p2",
        name: "Ridgeline Lodge",
        slug: "ridgeline-lodge",
        property_type: "mountain_home",
        bedrooms: 5,
        bathrooms: 4,
        max_guests: 12,
        address: "123 Ridge Road, Blue Ridge, GA",
        wifi_ssid: "RidgelineFast",
        access_code_type: "smart_lock",
        parking_instructions: "Driveway parking for three vehicles",
        is_active: true,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ];

    expect(buildAiListingRequest(properties)).toEqual({
      property_name: "Ridgeline Lodge",
      bedrooms: 5,
      bathrooms: 4,
      max_guests: 12,
      amenities: [
        "fast wifi",
        "self check-in",
        "dedicated parking",
        "large-group friendly",
        "mountain home",
      ],
      location: "123 Ridge Road, Blue Ridge, GA",
    });
  });

  it("falls back when no active properties are available", () => {
    expect(
      buildAiListingRequest([
        {
          id: "p1",
          name: "Archived Cabin",
          slug: "archived-cabin",
          property_type: "cabin",
          bedrooms: 2,
          bathrooms: 1,
          max_guests: 4,
          is_active: false,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ]),
    ).toEqual(DEFAULT_AI_INSIGHTS_LISTING_REQUEST);
  });
});
