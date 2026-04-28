/* Tablebuilder — BrowseModal: group → variable tree picker */

window.BrowseModal = function BrowseModal({ metadata, initialSelected, onApply, onCancel }) {
  const [selected, setSelected] = React.useState(new Set(initialSelected));
  const [openGroups, setOpenGroups] = React.useState(new Set());

  function toggleGroup(gid) {
    setOpenGroups(prev => {
      const next = new Set(prev);
      next.has(gid) ? next.delete(gid) : next.add(gid);
      return next;
    });
  }

  function toggleVar(vid) {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(vid) ? next.delete(vid) : next.add(vid);
      return next;
    });
  }

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h3>Browse variables</h3>
        <div className="modal-body">
          {metadata.groups.map(g => (
            <div key={g.id} className="browse-group">
              <button type="button" className="browse-group-header" onClick={() => toggleGroup(g.id)}>
                {openGroups.has(g.id) ? '▼' : '▶'} {g.label} ({g.variables.length})
              </button>
              {openGroups.has(g.id) && (
                <ul className="browse-vars">
                  {g.variables.map(v => (
                    <li key={v.id}>
                      <label>
                        <input
                          type="checkbox"
                          checked={selected.has(v.id)}
                          onChange={() => toggleVar(v.id)}
                          aria-label={v.label}
                        />
                        {v.label} <small>{v.code}</small>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
        <div className="modal-actions">
          <button type="button" onClick={onCancel}>Cancel</button>
          <button type="button" onClick={() => onApply(selected)}>Apply</button>
        </div>
      </div>
    </div>
  );
};
