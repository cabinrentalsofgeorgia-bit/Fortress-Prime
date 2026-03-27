import Image from "next/image";

export interface PropertyGalleryImage {
  id: string;
  legacy_url: string;
  sovereign_url?: string | null;
  alt_text: string;
  is_hero: boolean;
  status: string;
}

interface PropertyGalleryProps {
  images?: PropertyGalleryImage[] | null;
}

function resolveImageSrc(image: PropertyGalleryImage): string | null {
  const imageSrc = image.sovereign_url ? image.sovereign_url : image.legacy_url;
  return imageSrc.trim() || null;
}

function resolveImageAlt(image: PropertyGalleryImage): string {
  return image.alt_text.trim();
}

export function PropertyGallery({ images }: PropertyGalleryProps) {
  const renderableImages = (images ?? [])
    .map((image) => {
      const src = resolveImageSrc(image);
      if (!src) {
        return null;
      }
      return {
        ...image,
        src,
        alt: resolveImageAlt(image),
      };
    })
    .filter((image): image is PropertyGalleryImage & { src: string; alt: string } => image !== null);

  if (renderableImages.length === 0) {
    return null;
  }

  const heroImage =
    renderableImages.find((image) => image.is_hero) ?? renderableImages[0];
  const galleryImages = renderableImages.filter((image) => image.id !== heroImage.id);

  return (
    <section className="mx-auto max-w-7xl px-4 pt-10 sm:px-6 lg:px-8">
      <div className="space-y-4">
        <div className="relative aspect-[16/9] overflow-hidden rounded-[2rem] border border-slate-200 bg-slate-100 shadow-sm">
          <Image
            src={heroImage.src}
            alt={heroImage.alt}
            fill
            priority
            sizes="(max-width: 1280px) 100vw, 1280px"
            className="object-cover"
          />
        </div>

        {galleryImages.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {galleryImages.map((image) => (
              <div
                key={image.id}
                className="relative aspect-[4/3] overflow-hidden rounded-[1.5rem] border border-slate-200 bg-slate-100 shadow-sm"
              >
                <Image
                  src={image.src}
                  alt={image.alt}
                  fill
                  sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 25vw"
                  className="object-cover"
                />
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
