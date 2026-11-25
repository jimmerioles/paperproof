(() => {
  const uploadForm = document.getElementById("upload-form");
  const fileInput = document.getElementById("file-input");
  const fileCount = document.getElementById("file-count");
  const dropzone = document.getElementById("dropzone");

  const updateCount = () => {
    if (!fileInput || !fileCount) return;
    const count = fileInput.files ? fileInput.files.length : 0;
    fileCount.textContent =
      count === 0 ? "No files chosen" : `${count} file${count === 1 ? "" : "s"} ready`;
  };

  if (fileInput) {
    fileInput.addEventListener("change", updateCount);
    updateCount();
  }

  if (dropzone && fileInput) {
    ["dragenter", "dragover"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.add("is-dragging");
      });
    });
    ["dragleave", "drop"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.remove("is-dragging");
      });
    });
    dropzone.addEventListener("drop", (event) => {
      const dropped = event.dataTransfer ? Array.from(event.dataTransfer.files) : [];
      const pdfs = dropped.filter((file) => file.name.toLowerCase().endsWith(".pdf"));
      if (!pdfs.length) return;
      const transfer = new DataTransfer();
      pdfs.forEach((file) => transfer.items.add(file));
      fileInput.files = transfer.files;
      updateCount();
    });
  }

  if (uploadForm) {
    uploadForm.addEventListener("submit", () => {
      const button = uploadForm.querySelector('button[type="submit"]');
      if (button) {
        button.disabled = true;
        button.textContent = "Ingesting documents…";
      }
      uploadForm.classList.add("is-busy");
    });
  }

  document.querySelectorAll("form.sample-form").forEach((form) => {
    form.addEventListener("submit", () => {
      const button = form.querySelector("button");
      if (button) {
        button.disabled = true;
        button.textContent = "Building sample corpus…";
      }
    });
  });

  document.querySelectorAll("[data-dismiss-flash]").forEach((button) => {
    button.addEventListener("click", () => {
      const flash = button.closest(".flash");
      if (flash) flash.remove();
    });
  });

  const desk = document.querySelector("[data-desk]");
  if (!desk) return;

  const docId = desk.dataset.doc;
  const pageCount = Number(desk.dataset.pageCount || 1);
  const image = document.getElementById("page-image");
  const highlights = document.getElementById("highlights");
  const counter = document.getElementById("page-counter");
  const quoteElement = document.getElementById("caption-quote");
  const tabElement = document.getElementById("caption-tab");
  const noteElement = document.getElementById("caption-note");
  const prevButton = document.querySelector("[data-page-prev]");
  const nextButton = document.querySelector("[data-page-next]");

  if (!image || !highlights || !counter || !quoteElement || !tabElement || !noteElement) {
    return;
  }

  const records = Array.from(document.querySelectorAll("[data-record]"));
  const emptyCaption = "Select a cited term to see its clause.";

  const renderBoxes = (boxes) => {
    highlights.replaceChildren();
    boxes.forEach((box) => {
      const mark = document.createElement("span");
      mark.className = "highlight";
      mark.style.left = `${Number(box.left) || 0}%`;
      mark.style.top = `${Number(box.top) || 0}%`;
      mark.style.width = `${Number(box.width) || 0}%`;
      mark.style.height = `${Number(box.height) || 0}%`;
      highlights.appendChild(mark);
    });
  };

  const setPage = (page) => {
    const target = Math.min(Math.max(Number(page) || 1, 1), pageCount);
    image.src = `/documents/${docId}/pages/${target}.png`;
    image.alt = `Page ${target} of ${pageCount}`;
    counter.textContent = `${target} / ${pageCount}`;
    tabElement.textContent = `p. ${target}`;
    noteElement.textContent = `PDF page ${target}`;
    quoteElement.textContent = emptyCaption;
    renderBoxes([]);
    records.forEach((record) => record.classList.remove("is-selected"));
  };

  records.forEach((record) => {
    const button = record.querySelector("[data-select]");
    if (!button || button.disabled) return;
    button.addEventListener("click", () => {
      const page = Number(record.dataset.page || 1);
      const quote = record.dataset.quote || "";
      let boxes = [];
      try {
        boxes = JSON.parse(record.dataset.boxes || "[]");
      } catch {
        boxes = [];
      }
      image.src = `/documents/${docId}/pages/${page}.png`;
      image.alt = `Page ${page} of ${pageCount}`;
      counter.textContent = `${page} / ${pageCount}`;
      tabElement.textContent = `p. ${record.dataset.printed || page}`;
      noteElement.textContent = record.dataset.pageNote || `PDF page ${page}`;
      quoteElement.textContent = quote ? `“${quote}”` : emptyCaption;
      renderBoxes(Array.isArray(boxes) ? boxes : []);
      records.forEach((other) => other.classList.toggle("is-selected", other === record));
    });
  });

  if (prevButton) {
    prevButton.addEventListener("click", () => {
      const current = Number((counter.textContent || "1").split("/")[0].trim()) || 1;
      setPage(current - 1);
    });
  }

  if (nextButton) {
    nextButton.addEventListener("click", () => {
      const current = Number((counter.textContent || "1").split("/")[0].trim()) || 1;
      setPage(current + 1);
    });
  }
})();
