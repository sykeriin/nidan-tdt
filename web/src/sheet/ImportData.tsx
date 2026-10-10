// Load a real data file (CSV / Excel) into the twin: POST /api/datasets maps the columns, runs the twin and the
// analytics on the backend, caches the run and registers it; the sheet then switches to it.
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { uploadDataset } from "../api/client";

export function ImportData({ onLoaded }: { onLoaded: (id: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [estimate, setEstimate] = useState(false);
  const [status, setStatus] = useState<{ busy: boolean; msg: string | null; err: boolean }>({ busy: false, msg: null, err: false });
  const qc = useQueryClient();

  const send = async (files: FileList | null) => {
    if (!files?.length) return;
    const names = [...files].map((f) => f.name).join(", ");
    setStatus({ busy: true, msg: `Running the twin on ${names}…`, err: false });
    try {
      const ds = await uploadDataset([...files], estimate);
      await qc.invalidateQueries({ queryKey: ["datasets"] });
      setStatus({ busy: false, msg: `Loaded ${ds.rows} rows (${ds.mode})`, err: false });
      onLoaded(ds.dataset_id);
    } catch (e) {
      setStatus({ busy: false, msg: (e as Error).message, err: true });
    } finally {
      if (input.current) input.current.value = "";
    }
  };

  return (
    <div className="import">
      <span className="dataset-label">Your data</span>
      <div className="import-row">
        <button onClick={() => input.current?.click()} disabled={status.busy}>{status.busy ? "Loading…" : "Load file"}</button>
        <label title="Use for a transformer other than Transformer-1: the rating is estimated from the currents">
          <input type="checkbox" checked={estimate} onChange={(e) => setEstimate(e.target.checked)} /> other transformer
        </label>
      </div>
      <input ref={input} type="file" multiple hidden accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls"
        onChange={(e) => send(e.target.files)} />
      {status.msg && <p className={`import-msg${status.err ? " err" : ""}`} role={status.err ? "alert" : "status"}>{status.msg}</p>}
    </div>
  );
}
