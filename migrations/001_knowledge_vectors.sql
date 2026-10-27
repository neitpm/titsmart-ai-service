-- migrations/001_knowledge_vectors.sql
-- Extension, bảng lưu trữ vector và chính sách bảo mật RLS cho pgvector
-- Lưu ý: Chỉ là file migration định nghĩa schema, chưa tự động apply vào DB

-- 1. Bật extension pgvector
create extension if not exists vector;

-- 2. Tạo bảng lưu trữ vector tài liệu
create table if not exists knowledge_vectors (
    id text primary key,
    content text not null,
    embedding vector(384) not null,
    source_table text not null check (source_table in ('field_logs', 'issues', 'tasks')),
    record_id text not null,
    project_code text not null check (length(trim(project_code)) > 0),
    chunk_index int not null default 0,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint uq_knowledge_vectors_chunk unique (source_table, record_id, chunk_index)
);

-- 3. Tạo index phục vụ tìm kiếm và lọc dữ liệu
create index if not exists idx_knowledge_vectors_project_code on knowledge_vectors (project_code);
create index if not exists idx_knowledge_vectors_source_record on knowledge_vectors (source_table, record_id);

-- 4. Bật Row Level Security (RLS) để cô lập quyền truy cập theo dự án
alter table knowledge_vectors enable row level security;

-- 5. Policy RLS: Cho phép người dùng (auth.uid()) đọc vector của dự án mà họ là thành viên
-- Hỗ trợ cả 2 schema phổ biến trong hệ thống TITSmart:
-- a) Bảng liên kết project_members (project_id, user_id)
-- b) Thẻ [MEMBERS:uuid1,uuid2] lưu trực tiếp trong projects.notes
create policy "Users can only read vectors of assigned projects"
on knowledge_vectors
for select
using (
    exists (
        select 1 from projects p
        where p.code = knowledge_vectors.project_code
          and (
              -- Kiểm tra qua bảng project_members nếu có
              exists (
                  select 1 from project_members pm
                  where pm.project_id = p.id
                    and (pm.user_id = auth.uid() or pm.engineer_id = auth.uid())
              )
              -- Hoặc kiểm tra qua thẻ tag [MEMBERS:...] trong trường notes
              or p.notes ilike ('%[MEMBERS:%' || auth.uid()::text || '%]%')
              -- Hoặc là người quản lý dự án (manager_id)
              or p.manager_id = auth.uid()
          )
    )
);

-- 6. Policy RLS: Chặn tuyệt đối người dùng thường INSERT/UPDATE/DELETE vector
-- Chỉ service role (hoặc worker backend nội bộ) mới có quyền ghi/xóa vector
create policy "Only service role can mutate vectors"
on knowledge_vectors
for all
to service_role
using (true)
with check (true);
