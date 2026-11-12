"use client";

// Renders a coordinator tool result: one block per cloud agent that answered,
// labelled with the cloud, framework and model that built its A2UI surfaces.

import React from "react";
import dynamic from "next/dynamic";

const A2uiMessages = dynamic(
  () => import("@/components/A2uiMessages").then((m) => m.A2uiMessages),
  { ssr: false },
);

const CLOUD_NAMES: Record<string, string> = {
  gcp: "Google Cloud",
  aws: "AWS",
  azure: "Azure",
};

export type MeshSource = {
  cloud: string;
  framework?: string;
  model?: string;
  seconds?: number;
  text?: string;
  error?: string | null;
  validated_a2ui_json?: unknown[];
};

export function extractMeshSources(result: unknown): MeshSource[] | null {
  let value: any = result;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return null;
    }
  }
  return Array.isArray(value?.sources) ? value.sources : null;
}

export function MeshSources({ sources }: { sources: MeshSource[] }) {
  return (
    <div className="mesh-sources w-full space-y-3">
      {sources.map((s) => (
        <div key={s.cloud} className="mesh-source">
          <p className="text-xs text-slate-400 mb-1" data-cloud={s.cloud}>
            {CLOUD_NAMES[s.cloud] ?? s.cloud} · {s.framework} · {s.model}
            {typeof s.seconds === "number" ? ` · ${s.seconds.toFixed(1)} s` : ""}
          </p>
          {s.validated_a2ui_json && s.validated_a2ui_json.length > 0 ? (
            <A2uiMessages messages={s.validated_a2ui_json} />
          ) : (
            <p className="text-sm">{s.error ? `Error: ${s.error}` : s.text}</p>
          )}
        </div>
      ))}
    </div>
  );
}
