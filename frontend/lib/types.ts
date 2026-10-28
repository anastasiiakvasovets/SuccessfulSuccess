// Mirrors the Pydantic schemas in backend/app/schemas/meeting.py.

export type Participant = {
  id: string
  name: string
  email: string | null
  position: number
}

export type Meeting = {
  id: string
  name: string
  description: string | null
  location: string | null
  starts_at: string
  ends_at: string
  participants: Participant[]
  agenda: Agenda | null
  created_at: string
  updated_at: string
}

export type AgendaItem = {
  topic: string
  owner: string | null
  minutes: number | null
}

export type ActionItem = {
  task: string
  owner: string | null
  /** YYYY-MM-DD */
  due: string | null
}

export type Agenda = {
  items: AgendaItem[]
  action_items: ActionItem[]
}

/** What the agenda parser returns: a suggestion the user checks before saving. */
export type ParsedAgenda = Agenda & {
  title: string | null
  /** ISO 8601 with the user's offset, when the text says when */
  starts_at: string | null
  duration_minutes: number | null
  language: string
}

export type AgendaParseResult = {
  agenda: ParsedAgenda
  model: string
  prompt_version: string
}

/** Saving an agenda; the ai_* fields are set when it started from a suggestion. */
export type AgendaSaveInput = Agenda & {
  ai_suggestion?: ParsedAgenda | null
  ai_model?: string | null
  ai_prompt_version?: string | null
}

export type MeetingList = {
  items: Meeting[]
  total: number
  limit: number
  offset: number
  date: string
}

export type ParticipantInput = {
  name: string
  email?: string | null
}

export type MeetingCreateInput = {
  name: string
  description?: string | null
  location?: string | null
  starts_at: string
  ends_at: string
  participants: ParticipantInput[]
}

export type ApiErrorDetail = {
  field: string
  message: string
}

export type ApiErrorBody = {
  error: {
    code: string
    message: string
    details: ApiErrorDetail[]
  }
}

export type UserProfile = {
  id: string
  email: string | null
  email_verified: boolean
  name: string | null
  given_name: string | null
  family_name: string | null
  picture_url: string | null
  auth_provider: string
  created_at: string
  updated_at: string
  last_login_at: string | null
}
