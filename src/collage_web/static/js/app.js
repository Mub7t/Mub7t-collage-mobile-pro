document.addEventListener("DOMContentLoaded", () => {
  const fileInput = document.querySelector('input[type="file"][name="images"]');
  if (!fileInput) return;
  fileInput.addEventListener("change", () => {
    const count = fileInput.files?.length || 0;
    if (count > 0) {
      fileInput.title = `${count} files selected`;
    }
  });
});
