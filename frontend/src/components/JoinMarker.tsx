import * as Menu from "@radix-ui/react-dropdown-menu";
import { Equal, Link2, Scissors } from "lucide-react";
import { api, Join, Node } from "../api";
import { useP } from "../lib";
import { cn, Tip } from "../ui";

export const JOINS: { value: Exclude<Join, "">; label: string; short: string; does: string }[] = [
  { value: "continues", label: "Continues", short: "Same shot", does: "This clip begins on the very last picture of the clip before: the same place, people, pose, light and framing. The cut between them is hard, so the shot looks unbroken." },
  { value: "same_scene", label: "Same scene", short: "New angle", does: "The same place and people, but a new angle or a later moment. The look, light and props are kept; the first picture is new." },
  { value: "cut", label: "Cut", short: "New place or time", does: "A new place or a jump in time. Nothing is carried over from the clip before." },
];

export function joinOf(node: Node, hasLink: "continues" | "same_scene" | ""): Join {
  return node.continuity?.join || hasLink || "";
}

/** The small marker between two clips: chain = continues, equals = same scene, scissors = cut. Click it to change how the clip joins the one before. */
export default function JoinMarker({ node, depth }: { node: Node; depth: number }) {
  const P = useP();
  const p = P.view!.project;
  const link = p.dependencies.find((d) => d.to_id === node.id && (d.type === "continues_from" || d.type === "same_location"));
  const join = joinOf(node, link ? (link.type === "continues_from" ? "continues" : "same_scene") : "");
  const decided = JOINS.find((j) => j.value === join);
  const measured = node.continuity?.difference;
  const flagged = (P.view!.summary.continuity || []).some((f) => f.node === node.id && f.code === "join_measured");
  const Icon = join === "continues" ? Link2 : join === "same_scene" ? Equal : Scissors;
  const item = "flex cursor-pointer flex-col gap-0.5 rounded-md px-2 py-1.5 text-xs outline-none data-[highlighted]:bg-sunken";
  return (
    <div className="flex items-center gap-1 py-px" style={{ paddingLeft: 30 + depth * 14 }}>
      <Menu.Root>
        <Menu.Trigger asChild>
          <button data-help="join-marker" aria-label={`How this clip joins the clip before it: ${decided?.label || "not decided"}. Click to change.`} onClick={(e) => e.stopPropagation()}
            className={cn("flex items-center gap-1 rounded-full border px-1.5 py-px text-[10px] leading-4 hover:border-brand/50",
              flagged ? "border-bad/50 text-bad" : join === "continues" ? "border-info/40 text-info" : "border-line text-muted")}>
            <Icon className="h-2.5 w-2.5" />{decided ? decided.short : "not decided"}
          </button>
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content align="start" className="z-50 w-72 rounded-xl border border-line bg-panel p-1 shadow-pop" onClick={(e) => e.stopPropagation()}>
            <div className="px-2 py-1.5 text-[11px] text-muted">How does this clip join the clip before it?{node.continuity?.join_reason ? ` Now: ${node.continuity.join_reason}.` : ""}</div>
            {JOINS.map((j) => (
              <Menu.Item key={j.value} className={cn(item, join === j.value && "bg-brand/10")} onSelect={() => P.act("Save", () => api.setJoin(P.pid, node.id, j.value))}>
                <span className="font-medium">{j.label}{join === j.value ? " ✓" : ""}</span>
                <span className="text-[11px] text-muted">{j.does}</span>
              </Menu.Item>
            ))}
            {join === "continues" && <div className="px-2 py-1.5 text-[11px] text-muted">{measured == null ? "The first picture is compared with the last picture of the clip before once both are made." : `Measured difference ${measured.toFixed(2)} (0 = the same picture).`}</div>}
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      {flagged && <Tip content="This clip does not start where the clip before it ended. Open it to fix this."><span className="text-[10px] text-bad">does not match</span></Tip>}
    </div>
  );
}
