type OperationLike = "idle" | "loading" | "success" | "error" | string

const SUCCESS_WORDS = /\b(generated|regenerated|saved|approved|created|updated|uploaded|confirmed|rechecked|optimized)\b/i

export function statusMessageClass(operation: OperationLike, message = "") {
  if (operation === "error") return "bg-destructive/10 text-destructive"
  if (SUCCESS_WORDS.test(message)) return "bg-confirm/15 text-confirm"
  return "bg-muted text-muted-foreground"
}
