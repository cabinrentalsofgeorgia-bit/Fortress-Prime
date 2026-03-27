import { permanentRedirect } from "next/navigation";

type PageParams = { slug: string };

export const revalidate = 0;

export default async function ReviewArchivePage(
  { params }: { params: Promise<PageParams> | PageParams },
) {
  const { slug } = await Promise.resolve(params);
  permanentRedirect(`/reviews/${slug}`);
}
