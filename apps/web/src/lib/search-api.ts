import type { AgreementScope } from "@/lib/agreement-api";

export type SearchResult = {
  agreement_id: string;
  agreement_title: string;
  agreement_type: string;
  agreement_status: string;
  content_preview: string;
  citation: {
    chunk_id: string;
    anchor_ids: string[];
    source_checksum: string;
    source_version: string;
  };
  navigation: {
    agreement_id: string;
    anchor_ids: string[];
  };
  lexical_rank: number | null;
  semantic_rank: number | null;
  fused_score: number;
  index_provenance: {
    build_id: string;
    chunker_version: string;
    source_checksum: string;
    embedding_index_version: string | null;
  };
};

export type SearchResponse = {
  items: SearchResult[];
  limit: number;
};

export type SearchAgreementsOptions = {
  scope: AgreementScope;
  query: string;
  token?: string;
  baseUrl?: string;
  fetcher?: typeof fetch;
};

const defaultBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

export async function searchAgreements({
  scope,
  query,
  token,
  baseUrl = defaultBaseUrl,
  fetcher = fetch,
}: SearchAgreementsOptions): Promise<SearchResponse> {
  const params = new URLSearchParams({
    organization_id: scope.organizationId,
    workspace_id: scope.workspaceId,
    query,
  });
  const response = await fetcher(
    `${baseUrl.replace(/\/$/, "")}/search?${params.toString()}`,
    {
      cache: "no-store",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  );
  if (!response.ok) {
    throw new Error("Search is currently unavailable.");
  }
  return response.json() as Promise<SearchResponse>;
}
