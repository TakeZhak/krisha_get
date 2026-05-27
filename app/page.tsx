"use client";

import { FormEvent, useState } from "react";

const defaultValues = {
  startUrl: "https://krisha.kz/prodazha/kvartiry/",
  pages: "2",
  limit: "30",
  delayMin: "1",
  delayMax: "2.5",
  outputName: "krisha_export.csv"
};

export default function HomePage() {
  const [startUrl, setStartUrl] = useState(defaultValues.startUrl);
  const [pages, setPages] = useState(defaultValues.pages);
  const [limit, setLimit] = useState(defaultValues.limit);
  const [delayMin, setDelayMin] = useState(defaultValues.delayMin);
  const [delayMax, setDelayMax] = useState(defaultValues.delayMax);
  const [outputName, setOutputName] = useState(defaultValues.outputName);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showValidation, setShowValidation] = useState(false);

  const numericValidation = {
    pages: pages.trim() === "",
    limit: limit.trim() === "",
    delayMin: delayMin.trim() === "",
    delayMax: delayMax.trim() === ""
  };

  const hasValidationErrors = Object.values(numericValidation).some(Boolean);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setShowValidation(true);

    if (hasValidationErrors) {
      return;
    }

    const pagesValue = Number(pages);
    const limitValue = Number(limit);
    const delayMinValue = Number(delayMin);
    const delayMaxValue = Number(delayMax);

    if (
      Number.isNaN(pagesValue) ||
      Number.isNaN(limitValue) ||
      Number.isNaN(delayMinValue) ||
      Number.isNaN(delayMaxValue)
    ) {
      setError("Проверьте числовые поля: заполните их корректными числами.");
      return;
    }

    setLoading(true);

    try {
      const response = await fetch("/api/scrape", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          startUrl,
          pages: pagesValue,
          limit: limitValue,
          delayMin: delayMinValue,
          delayMax: delayMaxValue
        })
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.error ?? "Не удалось получить CSV");
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = outputName.endsWith(".csv")
        ? outputName
        : `${outputName}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Неизвестная ошибка"
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="container">
      <h1>Krisha Parser</h1>
      <p className="sub">
        Введите параметры и нажмите кнопку, чтобы скачать CSV (Excel-совместимый
        формат с разделителем <b>;</b>).
      </p>

      <form onSubmit={onSubmit}>
        <div className="grid">
          <div className="field full">
            <label htmlFor="startUrl">Ссылка на поиск (квартиры/коммерция)</label>
            <input
              id="startUrl"
              value={startUrl}
              onChange={(e) => setStartUrl(e.target.value)}
              required
            />
          </div>

          <div className="field">
            <label htmlFor="pages">Сколько страниц обходить</label>
            <input
              id="pages"
              type="number"
              min={1}
              max={30}
              value={pages}
              onChange={(e) => setPages(e.target.value)}
              className={showValidation && numericValidation.pages ? "input-error" : ""}
              required
            />
            {showValidation && numericValidation.pages ? (
              <span className="field-error">Нельзя оставлять пустым</span>
            ) : null}
          </div>

          <div className="field">
            <label htmlFor="limit">Лимит объявлений (0 = без лимита)</label>
            <input
              id="limit"
              type="number"
              min={0}
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              className={showValidation && numericValidation.limit ? "input-error" : ""}
              required
            />
            {showValidation && numericValidation.limit ? (
              <span className="field-error">Нельзя оставлять пустым</span>
            ) : null}
          </div>

          <div className="field">
            <label htmlFor="delayMin">Задержка мин (сек)</label>
            <input
              id="delayMin"
              type="number"
              min={0}
              step={0.1}
              value={delayMin}
              onChange={(e) => setDelayMin(e.target.value)}
              className={showValidation && numericValidation.delayMin ? "input-error" : ""}
              required
            />
            {showValidation && numericValidation.delayMin ? (
              <span className="field-error">Нельзя оставлять пустым</span>
            ) : null}
          </div>

          <div className="field">
            <label htmlFor="delayMax">Задержка макс (сек)</label>
            <input
              id="delayMax"
              type="number"
              min={0}
              step={0.1}
              value={delayMax}
              onChange={(e) => setDelayMax(e.target.value)}
              className={showValidation && numericValidation.delayMax ? "input-error" : ""}
              required
            />
            {showValidation && numericValidation.delayMax ? (
              <span className="field-error">Нельзя оставлять пустым</span>
            ) : null}
          </div>

          <div className="field full">
            <label htmlFor="outputName">Имя файла</label>
            <input
              id="outputName"
              value={outputName}
              onChange={(e) => setOutputName(e.target.value)}
              required
            />
          </div>
        </div>

        <button type="submit" disabled={loading}>
          {loading ? "Собираю данные..." : "Загрузить в Excel (CSV)"}
        </button>
      </form>

      <p className="hint">
        Поля в выгрузке: <b>url</b>, <b>price</b>, <b>address</b>, <b>area_m2</b>,
        <b>author_name</b>, <b>author_company</b>.
      </p>

      {error ? <p className="error">{error}</p> : null}
    </main>
  );
}
