export type AgentRequestSpec = {
  method: "GET" | "POST";
  path: string;
  forwardQuery?: boolean;
  forwardBody?: boolean;
};

export function agentRequestSpec(
  method: string,
  action: string | null,
  searchParams?: URLSearchParams
): AgentRequestSpec | null;
