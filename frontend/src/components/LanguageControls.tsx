import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api } from "../api";
import { HelpTip, Select } from "../ui";

/** The languages the tool offers (code and name). Asked once. */
export function useLanguages() {
  return useQuery({ queryKey: ["languages"], queryFn: api.languages, staleTime: Infinity });
}

export const SUBTITLE_OPTIONS = [
  { value: "spoken", label: "The spoken words" },
  { value: "english", label: "English meaning" },
  { value: "both", label: "Both" },
];

/** True when the video may have speech that is not English, so an English meaning is worth showing. "auto" = not decided yet, so yes. */
export function mayBeNonEnglish(language: string, also: string[]) {
  return language !== "en" || also.length > 0;
}

/**
 * The language of the SPOKEN words, and (for a mixed-language video) the other languages spoken somewhere.
 * Everything else the tool writes stays in English; the help text on the label says so.
 */
export function SpokenLanguage({ language, also, onLanguage, onAlso, className }: {
  language: string; also: string[]; onLanguage: (code: string) => void; onAlso: (codes: string[]) => void; className?: string;
}) {
  const langs = useLanguages();
  const all = langs.data || [];
  const nameOf = (c: string) => all.find((l) => l.code === c)?.name || c;
  const mainOptions = [{ value: "auto", label: "Decided from your goal" }, ...all.map((l) => ({ value: l.code, label: l.name })),
    ...(language !== "auto" && !all.some((l) => l.code === language) ? [{ value: language, label: language }] : [])];
  const addable = all.filter((l) => l.code !== language && !also.includes(l.code));
  return (
    <span className={className ?? "inline-flex flex-wrap items-center gap-x-4 gap-y-1.5"}>
      <label className="flex items-center gap-1.5">
        <HelpTip id="language-picker"><span>Spoken language</span></HelpTip>
        <Select title="Language of the spoken words" value={language} onChange={onLanguage} options={mainOptions} />
      </label>
      <span className="flex flex-wrap items-center gap-1.5" aria-label="Other languages also spoken in this video">
        <HelpTip id="also-spoken"><span>Also spoken</span></HelpTip>
        {also.map((c) => (
          <span key={c} className="inline-flex items-center gap-1 rounded-md bg-sunken px-1.5 py-0.5 text-[11px] text-ink">
            {nameOf(c)}
            <button type="button" aria-label={`Remove ${nameOf(c)}`} className="text-muted hover:text-bad" onClick={() => onAlso(also.filter((x) => x !== c))}>
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <Select title="Add another spoken language" value="" onChange={(v) => { if (v) onAlso([...also, v]); }}
          options={[{ value: "", label: also.length ? "+ Add another" : "+ Add a language" }, ...addable.map((l) => ({ value: l.code, label: l.name }))]} />
      </span>
    </span>
  );
}

/** What the subtitles show when speech is not English. */
export function SubtitleChoice({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex items-center gap-1.5">
      <HelpTip id="subtitle-language"><span>Subtitles show</span></HelpTip>
      <Select title="What the subtitles show" value={value} onChange={onChange} options={SUBTITLE_OPTIONS} />
    </label>
  );
}
