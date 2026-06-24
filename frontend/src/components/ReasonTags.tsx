interface Props {
  tags: string[] | null | undefined;
  limit?: number;
}

export function ReasonTags({ tags, limit = 6 }: Props) {
  const visible = (tags ?? []).slice(0, limit);
  if (visible.length === 0) return <span className="muted">No drivers detected</span>;
  return (
    <div className="tag-row">
      {visible.map((tag) => (
        <span className="tag" key={tag}>
          {tag}
        </span>
      ))}
      {(tags?.length ?? 0) > limit ? <span className="tag">+{(tags?.length ?? 0) - limit}</span> : null}
    </div>
  );
}

