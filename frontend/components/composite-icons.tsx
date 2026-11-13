import { Clapperboard, Image as ImageIcon, Mic, NotebookPen, Plus } from "lucide-react"

// Two overlapping glyphs in one tile, so a single icon says "both kinds" at a glance.
function Tile({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span aria-hidden="true" className={`relative block size-12 shrink-0 rounded-lg ${className}`}>
      {children}
    </span>
  )
}

/** Pictures and videos can both be uploaded. */
export function MediaUploadIcon() {
  return (
    <Tile className="bg-gold text-gold-foreground">
      <ImageIcon className="absolute left-1.5 top-1.5 size-6" strokeWidth={2} />
      <Clapperboard className="absolute bottom-1.5 right-1.5 size-6 rounded-sm bg-gold" strokeWidth={2} />
      <Plus className="absolute -right-1.5 -top-1.5 size-4 rounded-full bg-gold-foreground p-0.5 text-gold" strokeWidth={3} />
    </Tile>
  )
}

/** Gather context by speaking and writing. */
export function GatherContextIcon() {
  return (
    <Tile className="bg-ai text-ai-foreground">
      <Mic className="absolute left-1.5 top-1.5 size-6" strokeWidth={2} />
      <NotebookPen className="absolute bottom-1.5 right-1.5 size-6 rounded-sm bg-ai" strokeWidth={2} />
    </Tile>
  )
}
