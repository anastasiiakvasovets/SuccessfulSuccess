"use client"

import { AlertCircle, Loader2, Plus, Sparkles, Wand2, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Textarea } from "@/components/ui/textarea"
import { useSaveAgenda } from "@/hooks/use-meetings"
import { ApiError, PARSER_MAX_CHARS, PARSER_URL, parseAgenda } from "@/lib/api"
import type {
  ActionItem,
  AgendaItem,
  AgendaParseResult,
  AgendaSaveInput,
  Meeting,
  ParsedAgenda,
} from "@/lib/types"

// Form rows hold strings, as the inputs do. `suggested` names the fields the
// model filled that the user has not touched since.
type ItemRow = {
  key: number
  topic: string
  owner: string
  minutes: string
  suggested: Partial<Record<"topic" | "owner" | "minutes", boolean>>
}
type ActionRow = {
  key: number
  task: string
  owner: string
  due: string
  suggested: Partial<Record<"task" | "owner" | "due", boolean>>
}

let lastKey = 0
const newKey = () => ++lastKey

const blankItem = (): ItemRow => ({ key: newKey(), topic: "", owner: "", minutes: "", suggested: {} })
const blankAction = (): ActionRow => ({ key: newKey(), task: "", owner: "", due: "", suggested: {} })

/** Rows for saved items (suggested = false) or the model's (only filled fields are marked). */
function itemRows(items: AgendaItem[], suggested: boolean): ItemRow[] {
  return items.map((item) => ({
    key: newKey(),
    topic: item.topic,
    owner: item.owner ?? "",
    minutes: item.minutes?.toString() ?? "",
    suggested: suggested
      ? { topic: !!item.topic, owner: !!item.owner, minutes: item.minutes != null }
      : {},
  }))
}

function actionRows(actions: ActionItem[], suggested: boolean): ActionRow[] {
  return actions.map((action) => ({
    key: newKey(),
    task: action.task,
    owner: action.owner ?? "",
    due: action.due ?? "",
    suggested: suggested
      ? { task: !!action.task, owner: !!action.owner, due: !!action.due }
      : {},
  }))
}

/** One clear message per way a parse can fail; the form below always works by hand. */
function parseErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Type the agenda below instead."
  switch (error.status) {
    case 0:
      return "Could not reach the agenda parser. Check your connection and try again."
    case 401:
      return "Your session has expired. Sign in again."
    case 413:
      return `The text is too long: paste at most ${PARSER_MAX_CHARS.toLocaleString()} characters.`
    case 422:
      return "No agenda found in this text. Type it below instead."
    case 429:
      return "The agenda parser is busy. Try again in a minute, or type the agenda below."
    case 503:
      return "The agenda parser is unavailable right now. Type the agenda below instead."
    default:
      return error.message
  }
}

/** The rest of what the text says (title, time, length): shown, never saved here. */
function suggestionExtras(agenda: ParsedAgenda): string[] {
  const extras: string[] = []
  if (agenda.title) extras.push(`“${agenda.title}”`)
  if (agenda.starts_at) {
    const startsAt = new Date(agenda.starts_at)
    extras.push(
      Number.isNaN(startsAt.getTime())
        ? agenda.starts_at
        : startsAt.toLocaleString(undefined, {
            weekday: "short",
            day: "numeric",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          }),
    )
  }
  if (agenda.duration_minutes) extras.push(`${agenda.duration_minutes} min`)
  return extras
}

type Errors = Record<string, string>

/** Checks the rows, drops the empty ones, and builds the save request. */
function toPayload(
  items: ItemRow[],
  actions: ActionRow[],
): { payload: Pick<AgendaSaveInput, "items" | "action_items">; errors: Errors } {
  const errors: Errors = {}
  const filledItems = items.filter((row) => row.topic.trim() || row.owner.trim() || row.minutes)
  const filledActions = actions.filter((row) => row.task.trim() || row.owner.trim() || row.due)
  filledItems.forEach((row, index) => {
    if (!row.topic.trim()) errors[`items.${index}.topic`] = "Topic is required"
    const minutes = Number(row.minutes)
    if (row.minutes && (!Number.isInteger(minutes) || minutes < 1 || minutes > 480)) {
      errors[`items.${index}.minutes`] = "1–480 minutes"
    }
  })
  filledActions.forEach((row, index) => {
    if (!row.task.trim()) errors[`action_items.${index}.task`] = "Task is required"
  })
  return {
    errors,
    payload: {
      items: filledItems.map((row) => ({
        topic: row.topic.trim(),
        owner: row.owner.trim() || null,
        minutes: row.minutes ? Number(row.minutes) : null,
      })),
      action_items: filledActions.map((row) => ({
        task: row.task.trim(),
        owner: row.owner.trim() || null,
        due: row.due || null,
      })),
    },
  }
}

function SuggestedBadge({ show }: { show?: boolean }) {
  if (!show) return null
  return (
    <Badge
      variant="secondary"
      className="tint-violet pointer-events-none absolute top-1/2 right-2 -translate-y-1/2"
    >
      <Sparkles aria-hidden />
      suggested
    </Badge>
  )
}

function FieldError({ message }: { message?: string }) {
  return message ? <p className="text-destructive text-xs">{message}</p> : null
}

/** Paste an agenda: the model suggests, the person checks and saves. */
export function AgendaDialog({
  open,
  onOpenChange,
  meeting,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  meeting?: Meeting
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-2xl">
        {/* Mounted on every open, so the form starts from the saved agenda. */}
        {meeting ? <AgendaEditor meeting={meeting} onClose={() => onOpenChange(false)} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function AgendaEditor({ meeting, onClose }: { meeting: Meeting; onClose: () => void }) {
  const saveAgenda = useSaveAgenda()
  const [text, setText] = useState("")
  const [parsing, setParsing] = useState(false)
  const [startedAt, setStartedAt] = useState(0)
  const [now, setNow] = useState(0)
  const [parseError, setParseError] = useState<string>()
  const [suggestion, setSuggestion] = useState<AgendaParseResult>()
  const [items, setItems] = useState<ItemRow[]>(() =>
    meeting.agenda?.items.length ? itemRows(meeting.agenda.items, false) : [blankItem()],
  )
  const [actions, setActions] = useState<ActionRow[]>(() =>
    actionRows(meeting.agenda?.action_items ?? [], false),
  )
  const [errors, setErrors] = useState<Errors>({})
  const abortRef = useRef<AbortController | null>(null)

  // A closed dialog stops paying for its parse.
  useEffect(() => () => abortRef.current?.abort(), [])

  // Ticks the "Reading the text… N s" counter while a parse runs.
  useEffect(() => {
    if (!parsing) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [parsing])
  const elapsed = Math.max(0, Math.floor((now - startedAt) / 1000))

  const tooLong = text.length > PARSER_MAX_CHARS

  const onParse = async () => {
    if (!text.trim() || tooLong) return
    const controller = new AbortController()
    abortRef.current = controller
    setParseError(undefined)
    setStartedAt(Date.now())
    setNow(Date.now())
    setParsing(true)
    try {
      const result = await parseAgenda(text, controller.signal)
      setSuggestion(result)
      setItems(result.agenda.items.length ? itemRows(result.agenda.items, true) : [blankItem()])
      setActions(actionRows(result.agenda.action_items, true))
      setErrors({})
    } catch (error) {
      if (!controller.signal.aborted) setParseError(parseErrorMessage(error))
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setParsing(false)
    }
  }

  const onCancelParse = () => {
    abortRef.current?.abort()
    setParseError("Cancelled. Paste again or type the agenda below.")
  }

  // Touching a field takes its "suggested" mark away: the value is the user's now.
  const updateItem = (index: number, patch: Partial<Omit<ItemRow, "key" | "suggested">>) =>
    setItems((rows) =>
      rows.map((row, i) => {
        if (i !== index) return row
        const suggested = { ...row.suggested }
        for (const field of Object.keys(patch)) delete suggested[field as keyof typeof suggested]
        return { ...row, ...patch, suggested }
      }),
    )
  const updateAction = (index: number, patch: Partial<Omit<ActionRow, "key" | "suggested">>) =>
    setActions((rows) =>
      rows.map((row, i) => {
        if (i !== index) return row
        const suggested = { ...row.suggested }
        for (const field of Object.keys(patch)) delete suggested[field as keyof typeof suggested]
        return { ...row, ...patch, suggested }
      }),
    )

  const onSave = async () => {
    const { payload, errors: found } = toPayload(items, actions)
    setErrors(found)
    if (Object.keys(found).length > 0) return
    const request: AgendaSaveInput = suggestion
      ? {
          ...payload,
          ai_suggestion: suggestion.agenda,
          ai_model: suggestion.model,
          ai_prompt_version: suggestion.prompt_version,
        }
      : payload
    try {
      await saveAgenda.mutateAsync({ id: meeting.id, payload: request })
      toast.success("Agenda saved")
      onClose()
    } catch (error) {
      if (error instanceof ApiError) {
        setErrors(Object.fromEntries(error.details.map((d) => [d.field, d.message])))
        toast.error(error.message)
      } else {
        toast.error("Could not save the agenda.")
      }
    }
  }

  const extras = suggestion ? suggestionExtras(suggestion.agenda) : []

  return (
    <>
      <DialogHeader>
        <DialogTitle>Agenda</DialogTitle>
        <DialogDescription>
          {meeting.name}
          {PARSER_URL ? " · Paste an email or notes to pre-fill it, then check and save." : null}
        </DialogDescription>
      </DialogHeader>

      {PARSER_URL ? (
        <section className="space-y-2">
          <Label htmlFor="agenda-paste">Paste an agenda</Label>
          <Textarea
            id="agenda-paste"
            rows={5}
            placeholder="Пн 10:00, синк по прайсингу, 45 хв. 1) нові тарифи Pro — Олена, 15 хв 2) …"
            value={text}
            disabled={parsing}
            aria-invalid={tooLong}
            onChange={(event) => setText(event.target.value)}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span
              className={`text-xs tabular-nums ${tooLong ? "text-destructive" : "text-muted-foreground"}`}
            >
              {text.length.toLocaleString()} / {PARSER_MAX_CHARS.toLocaleString()}
            </span>
            {parsing ? (
              <div className="flex items-center gap-3" role="status">
                <span className="text-muted-foreground inline-flex items-center gap-2 text-sm">
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  Reading the text… {elapsed} s
                </span>
                <Button type="button" variant="outline" size="sm" onClick={onCancelParse}>
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                type="button"
                size="sm"
                onClick={onParse}
                disabled={!text.trim() || tooLong}
              >
                <Wand2 aria-hidden />
                Parse
              </Button>
            )}
          </div>
          {parseError ? (
            <Alert variant="destructive">
              <AlertCircle aria-hidden />
              <AlertDescription>{parseError}</AlertDescription>
            </Alert>
          ) : null}
          {suggestion ? (
            <p className="text-muted-foreground text-xs">
              <Sparkles className="mr-1 inline size-3" aria-hidden />
              Pre-filled by {suggestion.model}. Check every field marked suggested.
              {extras.length > 0
                ? ` The text also mentions ${extras.join(" · ")}: change the meeting with Edit if that is right.`
                : null}
            </p>
          ) : null}
          <Separator className="my-4" />
        </section>
      ) : null}

      <section className="space-y-3">
        <h3 className="text-sm font-semibold">Items</h3>
        {items.map((row, index) => (
          <div key={row.key} className="space-y-2 rounded-lg border p-3">
            <div className="flex items-start gap-2">
              <div className="relative flex-1">
                <Input
                  aria-label={`Item ${index + 1} topic`}
                  placeholder="Topic"
                  className="pr-28"
                  value={row.topic}
                  aria-invalid={!!errors[`items.${index}.topic`]}
                  onChange={(event) => updateItem(index, { topic: event.target.value })}
                />
                <SuggestedBadge show={row.suggested.topic} />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove item ${index + 1}`}
                onClick={() => setItems((rows) => rows.filter((_, i) => i !== index))}
              >
                <X className="size-4" aria-hidden />
              </Button>
            </div>
            <FieldError message={errors[`items.${index}.topic`]} />
            <div className="grid grid-cols-2 gap-2 pr-11">
              <div className="relative">
                <Input
                  aria-label={`Item ${index + 1} owner`}
                  placeholder="Owner (optional)"
                  className="pr-28"
                  value={row.owner}
                  onChange={(event) => updateItem(index, { owner: event.target.value })}
                />
                <SuggestedBadge show={row.suggested.owner} />
              </div>
              <div className="relative">
                <Input
                  aria-label={`Item ${index + 1} minutes`}
                  placeholder="Minutes"
                  type="number"
                  min={1}
                  max={480}
                  className="pr-28"
                  value={row.minutes}
                  aria-invalid={!!errors[`items.${index}.minutes`]}
                  onChange={(event) => updateItem(index, { minutes: event.target.value })}
                />
                <SuggestedBadge show={row.suggested.minutes} />
              </div>
            </div>
            <FieldError message={errors[`items.${index}.minutes`]} />
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setItems((rows) => [...rows, blankItem()])}
        >
          <Plus className="size-4" aria-hidden />
          Add item
        </Button>
      </section>

      <section className="space-y-3">
        <h3 className="text-sm font-semibold">Action items</h3>
        {actions.length === 0 ? (
          <p className="text-muted-foreground text-sm">No action items.</p>
        ) : null}
        {actions.map((row, index) => (
          <div key={row.key} className="space-y-2 rounded-lg border p-3">
            <div className="flex items-start gap-2">
              <div className="relative flex-1">
                <Input
                  aria-label={`Action ${index + 1} task`}
                  placeholder="Task"
                  className="pr-28"
                  value={row.task}
                  aria-invalid={!!errors[`action_items.${index}.task`]}
                  onChange={(event) => updateAction(index, { task: event.target.value })}
                />
                <SuggestedBadge show={row.suggested.task} />
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove action ${index + 1}`}
                onClick={() => setActions((rows) => rows.filter((_, i) => i !== index))}
              >
                <X className="size-4" aria-hidden />
              </Button>
            </div>
            <FieldError message={errors[`action_items.${index}.task`]} />
            <div className="grid grid-cols-2 gap-2 pr-11">
              <div className="relative">
                <Input
                  aria-label={`Action ${index + 1} owner`}
                  placeholder="Owner (optional)"
                  className="pr-28"
                  value={row.owner}
                  onChange={(event) => updateAction(index, { owner: event.target.value })}
                />
                <SuggestedBadge show={row.suggested.owner} />
              </div>
              <div className="relative">
                <Input
                  aria-label={`Action ${index + 1} due date`}
                  type="date"
                  className="pr-28"
                  value={row.due}
                  onChange={(event) => updateAction(index, { due: event.target.value })}
                />
                <SuggestedBadge show={row.suggested.due} />
              </div>
            </div>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setActions((rows) => [...rows, blankAction()])}
        >
          <Plus className="size-4" aria-hidden />
          Add action item
        </Button>
      </section>

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="button" onClick={onSave} disabled={parsing || saveAgenda.isPending}>
          {saveAgenda.isPending ? <Loader2 className="animate-spin" aria-hidden /> : null}
          Save agenda
        </Button>
      </DialogFooter>
    </>
  )
}
