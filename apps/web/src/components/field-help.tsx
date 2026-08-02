import { useId } from "react";

type FieldHelpProps = {
  children: string;
};

export function FieldHelp({ children }: FieldHelpProps) {
  const tooltipId = useId();

  return (
    <span className="group relative inline-flex align-middle">
      <span
        aria-describedby={tooltipId}
        className="ml-1 inline-flex size-4 cursor-help items-center justify-center rounded-full border border-slate-400 text-[11px] font-bold text-slate-600"
        tabIndex={0}
      >
        ?
      </span>
      <span
        id={tooltipId}
        className="pointer-events-none absolute bottom-full left-0 z-10 mb-2 hidden w-72 rounded-lg bg-slate-950 px-3 py-2 text-xs font-normal leading-5 text-white shadow-lg group-focus-within:block group-hover:block"
        role="tooltip"
      >
        {children}
      </span>
    </span>
  );
}
