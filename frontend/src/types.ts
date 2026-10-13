export interface ContentBlock {
  id?: string; type?: string; kind?: string; text?: string; level?: number;
  path?: string; file_id?: string; caption?: string; width?: number; height?: number;
  headers?: unknown[]; rows?: unknown[][]; items?: unknown[]; marker?: string;
  blocks?: ContentBlock[];
}
export interface DocumentInfo {
  id: string; title: string; name: string; format: string; created_at: string;
  digest: string; chunk_count: number; question_count: number;
}
export interface Chunk {
  id: string; document_id: string; page: number; section: string; ordinal: number;
  completed: number; offset: number; favorite: number; text?: string;
  document_title?: string; format?: string;
}
export interface Source {
  chunk_id: string; document_id?: string; document_title?: string; page: number;
  section: string; quote: string; label?: string; format?: string;
}
export interface Attempt {id: string; correct: boolean; selected: number[]; created_at: string; mode: string;}
export interface Question {
  id: string; document_id: string; stem: string; options: string[]; sources: Source[];
  origin: string; reviewed: number; favorite: number; uncertain: number; draft: number[];
  multiple: boolean; revealed: boolean; latest: Attempt | null;
}
export interface AnswerResult {
  question_id: string; answer: number[]; selected: number[]; correct: boolean;
  explanation: string; mode: string; sources: Source[]; reference_only: boolean;
}
export interface Task {id: string; date: string; kind: string; target_id: string; completed: boolean;}
export interface ModelConfig {base_url: string; model: string; configured: boolean; has_key: boolean; allow_no_key: boolean; json_mode: boolean;}
export interface Chat {id: string; question: string; answer: string; sources: Source[]; supported: boolean; created_at: string; model: string;}
export interface AppState {
  documents: DocumentInfo[]; chunks: Chunk[]; questions: Question[]; chats: Chat[];
  plan: {id: string; title: string; days: number; daily_target: number} | null; tasks: Task[];
  model: ModelConfig; date: string; wrong_question_ids: string[];
  stats: {read: number; chunks: number; practiced: number; questions: number; correct: number; wrong: number; attempts_today: number; completed_today: number};
}
