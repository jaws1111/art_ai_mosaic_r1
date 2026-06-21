import { useEffect, useRef } from "react";

export interface LibraryEntry {
  id: string;
  title: string;
  category: string;
  thumbnail: string; // emoji stand-in
  prompt: string;
  style: string;
}

const LIBRARY: LibraryEntry[] = [
  {
    id: "landscape",
    title: "Epic Alpine Landscape",
    category: "Landscape",
    thumbnail: "🏔️",
    prompt:
      "A sweeping alpine valley at golden hour, a braided glacial river winding through meadows of wildflowers, ancient pine and larch forests climbing steep slopes, jagged snow-capped peaks piercing clouds, a rustic stone bridge in the middle ground, mist pooling in the hollows, warm amber and rose light catching every surface, birds of prey circling thermals, complete panoramic vista with foreground boulders and lichen, mid-ground meadow and river, background mountains and sky.",
    style: "cinematic landscape photography, Ansel Adams inspired, 8K ultra-detail, golden hour,",
  },
  {
    id: "portrait",
    title: "Grand Portrait Composition",
    category: "Portrait",
    thumbnail: "🎭",
    prompt:
      "An imposing full-length portrait of a Renaissance-era noblewoman, standing before an ornate arched window overlooking a sunlit courtyard garden, wearing an elaborate gown of deep crimson velvet with gold embroidery and a pearl-encrusted neckline, her expression regal and composed, rich fabrics cascading to the floor, a small pet greyhound at her feet, afternoon light streaming through leaded glass casting long golden shafts across the marble floor, painted in the style of a grand royal portrait.",
    style: "Old Masters oil painting, Vermeer lighting, rich jewel-tone palette, ultra fine detail,",
  },
  {
    id: "mass-event",
    title: "Massive Festival Crowd",
    category: "Mass Event",
    thumbnail: "🎉",
    prompt:
      "An enormous outdoor festival spanning a vast plaza in a Mediterranean city at sunset, tens of thousands of people gathered in dense celebratory crowds, performers on a massive central stage with towering light rigs and fireworks bursting overhead, vendors and market stalls lining the edges, flags and banners of every color, confetti raining down, the crowd a sea of raised hands and glowing phones, medieval cathedral and ancient city walls visible in the background, smoke from fireworks drifting across the sky.",
    style: "photojournalistic, aerial perspective, vibrant saturated color, documentary ultra-HD,",
  },
  {
    id: "space",
    title: "Interstellar Fleet Encounter",
    category: "Outer Space",
    thumbnail: "🚀",
    prompt:
      "A colossal interstellar warship, a kilometer-long dreadnought with glowing engine nacelles and bristling weapon turrets, emerging from a swirling blue-white hyperspace jump point in deep space, surrounded by a battle fleet of frigates and fighters in tight formation, the gas giant Kepler-452 looming enormous in the background with amber cloud bands and three moons, a distant nebula painting the cosmos in crimson and violet, stars streaked by relativistic motion, debris from a destroyed enemy vessel tumbling in the foreground.",
    style: "hard science fiction concept art, cinematic lighting, Syd Mead aesthetic, photorealistic VFX, 8K,",
  },
  {
    id: "naval-battle",
    title: "Age of Sail Naval Battle",
    category: "Ocean",
    thumbnail: "⚓",
    prompt:
      "A ferocious Age of Sail naval battle between two massive fleets, multi-deck ships of the line with full sail billowing, cannons firing broadside volleys shrouded in black powder smoke, tall masts splintering and sails ablaze, sailors climbing rigging and firing from crow's nests, a first-rate 100-gun flagship in the foreground exchanging fire at close range with an enemy three-decker, smaller frigates and sloops weaving between the giants, the sea churned white and strewn with wreckage and lifeboats, storm clouds building on the horizon, dramatic chiaroscuro light breaking through the gun smoke.",
    style: "maritime oil painting, J.M.W. Turner turbulent skies, Nicholas Pocock naval accuracy, epic scale, ultra-detail,",
  },
];

interface Props {
  onSelect: (entry: LibraryEntry) => void;
  onClose: () => void;
}

export default function PromptLibrary({ onSelect, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [onClose]);

  useEffect(() => {
    function handle(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handle);
    return () => document.removeEventListener("keydown", handle);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div
        ref={ref}
        className="w-[560px] max-h-[80vh] flex flex-col bg-[#16181f] border border-neutral-700 rounded-xl shadow-2xl"
      >
        {/* header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-neutral-800">
          <div>
            <h2 className="text-sm font-semibold text-neutral-100">Prompt Library</h2>
            <p className="text-[10px] text-neutral-500 mt-0.5">Click a scene to load it into the prompt field</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-neutral-500 hover:text-neutral-200 transition-colors text-lg leading-none"
          >
            ×
          </button>
        </div>

        {/* list */}
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {LIBRARY.map((entry) => (
            <button
              key={entry.id}
              type="button"
              onClick={() => onSelect(entry)}
              className="w-full text-left rounded-lg border border-neutral-700 bg-neutral-900 hover:border-accent hover:bg-accent/5 p-3 transition-all group"
            >
              <div className="flex items-start gap-3">
                <span className="text-2xl leading-none mt-0.5 select-none">{entry.thumbnail}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-semibold text-neutral-100 group-hover:text-white transition-colors">
                      {entry.title}
                    </span>
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-neutral-800 text-neutral-500 border border-neutral-700 uppercase tracking-wide shrink-0">
                      {entry.category}
                    </span>
                  </div>
                  <p className="text-[10px] text-neutral-500 leading-relaxed line-clamp-2">
                    {entry.prompt}
                  </p>
                  <p className="text-[9px] text-neutral-600 mt-1 italic truncate">
                    Style: {entry.style}
                  </p>
                </div>
              </div>
            </button>
          ))}
        </div>

        <div className="px-5 py-3 border-t border-neutral-800 text-[10px] text-neutral-600">
          Selecting a preset replaces both the prompt and style anchor.
        </div>
      </div>
    </div>
  );
}
