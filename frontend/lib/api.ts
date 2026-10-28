import { signOut } from "aws-amplify/auth"

import { getAccessToken } from "@/lib/auth"
import { toIsoDate } from "@/lib/datetime"
import type {
  AgendaParseResult,
  AgendaSaveInput,
  ApiErrorBody,
  ApiErrorDetail,
  Meeting,
  MeetingCreateInput,
  MeetingList,
  UserProfile,
} from "@/lib/types"

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"

/** The agenda parser's function URL (Lab 6). Empty hides "Paste an agenda". */
export const PARSER_URL = process.env.NEXT_PUBLIC_PARSER_URL ?? ""

/** Longest text the parser accepts; it answers 413 above this. */
export const PARSER_MAX_CHARS = 10_000

export class ApiError extends Error {
  readonly code: string
  readonly details: ApiErrorDetail[]
  readonly status: number

  constructor(status: number, code: string, message: string, details: ApiErrorDetail[]) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request<T>(path: string, init?: RequestInit, baseUrl = API_BASE_URL): Promise<T> {
  const token = await getAccessToken()
  let response: Response
  try {
    response = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
      cache: "no-store",
    })
  } catch (error) {
    // Cancelled by the caller (AbortController): not a network failure.
    if (init?.signal?.aborted) throw error
    throw new ApiError(0, "network_error", "Could not reach the meetings API.", [])
  }

  // The session is gone or was revoked: sign out, and the auth guard sends the
  // user back to the login page.
  if (response.status === 401) {
    void signOut()
  }

  if (response.status === 204) {
    return undefined as T
  }

  const text = await response.text()
  const payload = text ? JSON.parse(text) : null

  if (!response.ok) {
    const body = payload as ApiErrorBody | null
    throw new ApiError(
      response.status,
      body?.error?.code ?? "internal_error",
      body?.error?.message ?? `Request failed with status ${response.status}.`,
      body?.error?.details ?? [],
    )
  }

  return payload as T
}

export function listMeetings(params: { date?: string; q?: string } = {}) {
  const search = new URLSearchParams()
  if (params.date) search.set("date", params.date)
  if (params.q) search.set("q", params.q)
  const query = search.toString()
  return request<MeetingList>(`/api/v1/meetings${query ? `?${query}` : ""}`)
}

export function getMeeting(id: string) {
  return request<Meeting>(`/api/v1/meetings/${id}`)
}

export function createMeeting(payload: MeetingCreateInput) {
  return request<Meeting>("/api/v1/meetings", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function updateMeeting(id: string, payload: MeetingCreateInput) {
  return request<Meeting>(`/api/v1/meetings/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  })
}

/** Saves through the API with its usual validation; the parser never writes. */
export function saveAgenda(id: string, payload: AgendaSaveInput) {
  return request<Meeting>(`/api/v1/meetings/${id}/agenda`, {
    method: "PUT",
    body: JSON.stringify(payload),
  })
}

/**
 * Asks the parser for a suggested agenda. Sends the user's date and time zone,
 * because "Monday" means the user's Monday, not the server's.
 */
export function parseAgenda(text: string, signal?: AbortSignal) {
  return request<AgendaParseResult>(
    "",
    {
      method: "POST",
      body: JSON.stringify({
        text,
        today: toIsoDate(new Date()),
        tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }),
      signal,
    },
    PARSER_URL,
  )
}

export function deleteMeeting(id: string) {
  return request<void>(`/api/v1/meetings/${id}`, { method: "DELETE" })
}

export function getMe() {
  return request<UserProfile>("/api/v1/me")
}

/** Stores the profile from the ID token in the users table; call after signing in. */
export function syncMe(idToken: string) {
  return request<UserProfile>("/api/v1/me/sync", {
    method: "POST",
    body: JSON.stringify({ id_token: idToken }),
  })
}
