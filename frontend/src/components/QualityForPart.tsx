import { useQuery } from "@tanstack/react-query";
import { Gauge } from "lucide-react";
import { api, Node } from "../api";
import { fmtTime, fmtUsd, useP } from "../lib";
import { cn, HelpTip } from "../ui";

const NAMES: Record<string, string> = { best: "Best", balanced: "Balanced", budget: "Budget", free: "Free preview" };
const WHY: Record<string, string> = {
  best: "the highest quality models",
  balanced: "good quality for the money",
  budget: "the cheapest real models that are good enough",
  free: "free placeholder cards only",
};

/** "Quality for this part": choose Best, Balanced, Budget or Free for this part only (or leave it the same as the video), with the price of each beside it.
 *  The prices are worked out on a copy, so nothing is saved or spent until you choose. Voices, the narrator and the music stay the same for the whole video. */
export default function QualityForPart({ node, isRoot }: { node: Node; isRoot: boolean }) {
  const P = useP();
  const q = useQuery({ queryKey: ["mode-costs", P.pid, node.id, P.view?.project.updated_at], queryFn: () => api.modeCosts(P.pid, node.id), staleTime: 0 });
  const d = q.data;
  const own = isRoot ? P.view!.project.settings.quality_mode : (node.quality_mode || "");
  const choose = (v: string) => (isRoot
    ? P.act("Save", () => api.patch(P.pid, { settings: { quality_mode: v } }))
    : P.act("Save", () => api.patchNode(P.pid, node.id, { quality_mode: v })));
  const options = [...(isRoot ? [] : [""]), "best", "balanced", "budget", "free"];
  return (
    <div data-help="part-quality" className="rounded-xl border border-line p-3">
      <HelpTip id="part-quality">
        <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold"><Gauge className="h-3.5 w-3.5 text-brand" />Quality for {isRoot ? "the whole video" : "this part"}</div>
      </HelpTip>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5" role="radiogroup" aria-label="Quality">
        {options.map((v) => {
          const m = v ? d?.modes?.[v] : undefined;
          const selected = own === v;
          return (
            <button key={v || "inherit"} type="button" role="radio" aria-checked={selected} onClick={() => !selected && choose(v)}
              title={v ? `${NAMES[v]}: ${WHY[v]}` : "This part follows the quality of the part above it, or of the whole video"}
              className={cn("flex flex-col rounded-lg border px-2.5 py-2 text-left text-xs", selected ? "border-brand bg-brand/10" : "border-line hover:border-brand/40")}>
              <span className="font-medium">{v ? NAMES[v] : "Same as above"}</span>
              <span className="text-[11px] text-muted">
                {v ? (m ? `${fmtUsd(m.cost_todo)} · ~${fmtTime(m.time_s)}` : "…") : d ? `now ${NAMES[d.inherits] || d.inherits}` : "…"}
              </span>
            </button>
          );
        })}
      </div>
      <p className="mt-2 text-[11px] text-muted">
        The price is for the clips not made yet. This changes the video, picture and natural-sound models for {isRoot ? "every part" : "this part"} only.
        Voices, the narrator and the music are chosen once for the whole video, so every character sounds the same everywhere.
      </p>
    </div>
  );
}
