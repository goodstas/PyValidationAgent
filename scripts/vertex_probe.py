"""Verify the configured Vertex model using ADC; never print credentials."""

from google import genai

from secureyourcode.config import load_settings


def main() -> None:
    settings = load_settings()
    if settings.model_provider != "vertex":
        raise RuntimeError("Set MODEL_PROVIDER=vertex for this Vertex AI probe.")
    settings.require_model()
    with genai.Client(
        vertexai=True,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        http_options={"timeout": 60000},
    ) as client:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents="Reply with the single word OK.",
        )
        if not response.text:
            raise RuntimeError("Vertex returned no text; inspect the configured model and its access permissions.")
        print(f"Vertex request succeeded: project={settings.google_cloud_project}, "
              f"location={settings.google_cloud_location}, model={settings.gemini_model}")


if __name__ == "__main__":
    main()
