"use client";

import { useEffect, useRef, useState } from "react";
import { PatientSummary } from "@/lib/types";
import { getPatientName } from "@/lib/names";

interface Props {
    patients: PatientSummary[];       // initial order (shown before & during animation)
    finalOrder: PatientSummary[];     // agent's sorted order (animate toward this)
    isAnimating: boolean;
    disabled?: boolean;
}

const ESI_COLORS: Record<number, string> = {
    1: "#ff2d55", 2: "#ff6b00", 3: "#ffd60a", 4: "#30d158", 5: "#636366",
};

export function AnimatedQueue({ patients, finalOrder, isAnimating }: Props) {
    // displayOrder is the single source of truth for what's shown
    const [displayOrder, setDisplayOrder] = useState<PatientSummary[]>(patients);
    const [activeIdx, setActiveIdx] = useState<number | null>(null);

    // Ref to track ongoing animation — prevents new effect runs from interfering
    const animRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const isRunningRef = useRef(false);

    // Only reset to patients prop when NOT animating (e.g. fresh episode)
    useEffect(() => {
        if (!isAnimating && !isRunningRef.current) {
            setDisplayOrder(patients);
        }
    }, [patients, isAnimating]);

    // Animation effect — runs once when isAnimating flips to true
    useEffect(() => {
        if (!isAnimating || finalOrder.length === 0) return;
        if (isRunningRef.current) return; // already running, ignore re-trigger

        isRunningRef.current = true;

        // Capture the starting order at this moment (don't rely on prop later)
        const startOrder = patients.map((p) => ({ ...p }));

        // Derive bubble-sort swap steps from startOrder → finalOrder
        const target = finalOrder.map((p) => p.case_id);
        const working = startOrder.map((p) => p.case_id);
        const steps: [number, number][] = [];

        for (let i = 0; i < target.length; i++) {
            const curIdx = working.indexOf(target[i]);
            if (curIdx !== i) {
                for (let j = curIdx; j > i; j--) {
                    steps.push([j - 1, j]);
                    [working[j - 1], working[j]] = [working[j], working[j - 1]];
                }
            }
        }

        if (steps.length === 0) {
            setDisplayOrder([...finalOrder]);
            isRunningRef.current = false;
            return;
        }

        let stepIdx = 0;
        const current = [...startOrder];

        const runStep = () => {
            if (stepIdx >= steps.length) {
                setDisplayOrder([...finalOrder]);
                setActiveIdx(null);
                isRunningRef.current = false;
                return;
            }
            const [a, b] = steps[stepIdx];
            setActiveIdx(a);
            [current[a], current[b]] = [current[b], current[a]];
            // Replace the whole array reference so React detects the change
            setDisplayOrder(current.map((p) => ({ ...p })));
            stepIdx++;
            animRef.current = setTimeout(runStep, 500);
        };

        animRef.current = setTimeout(runStep, 400);

        return () => {
            if (animRef.current) clearTimeout(animRef.current);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isAnimating]); // ← intentionally only depends on isAnimating, not patients/finalOrder

    return (
        <div className="space-y-2">
            {displayOrder.map((p, idx) => (
                <div
                    key={`${p.case_id}-${idx}`}
                    className={`flex items-center gap-3 rounded-xl p-3 border transition-all duration-400
                        ${activeIdx === idx
                            ? "scale-[1.02] border-[#0a84ff]/60 bg-[#0a84ff]/10 shadow-[0_0_16px_#0a84ff22]"
                            : "border-white/8 bg-white/2"
                        }`}
                >
                    {/* rank badge */}
                    <div className="w-6 h-6 rounded-lg bg-white/6 flex items-center justify-center text-xs font-bold text-white/40 flex-shrink-0">
                        {idx + 1}
                    </div>

                    {/* status dot */}
                    {activeIdx === idx && isRunningRef.current ? (
                        <span className="w-2 h-2 rounded-full bg-[#0a84ff] animate-pulse flex-shrink-0" />
                    ) : (
                        <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: "#ffd60a" }} />
                    )}

                    {/* patient info */}
                    <div className="flex-1 min-w-0">
                        <div className="text-sm font-semibold text-white truncate">
                            {getPatientName(p.case_id, p.gender)}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-xs text-white/50">{p.age}y · {p.gender}</span>
                            <span className="text-[10px] font-mono text-white/20">{p.case_id}</span>
                        </div>
                        <div className="text-xs text-white/40 truncate mt-0.5">
                            {p.symptoms.slice(0, 2).join(", ")}{p.symptoms.length > 2 ? "…" : ""}
                        </div>
                    </div>

                    {/* moving indicator */}
                    {activeIdx === idx && isRunningRef.current && (
                        <span className="text-xs text-[#0a84ff] font-medium animate-pulse flex-shrink-0">↕ moving</span>
                    )}
                </div>
            ))}
        </div>
    );
}
