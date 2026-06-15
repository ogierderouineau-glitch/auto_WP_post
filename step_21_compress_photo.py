from PIL import Image
import os


def compress_image_to_target(
    input_path,
    output_path,
    target_kb=50,
    min_quality=25,
    start_quality=90,
    resize_step=0.9,
    min_width=300
):
    """
    Compress image to stay under target_kb.
    """

    target_bytes = target_kb * 1024

    img = Image.open(input_path)

    # Convert transparent PNG/WebP to white background JPEG
    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))

        if img.mode == "P":
            img = img.convert("RGBA")

        background.paste(
            img,
            mask=img.split()[-1] if img.mode == "RGBA" else None
        )

        img = background
    else:
        img = img.convert("RGB")

    width, height = img.size

    while True:
        # Try lowering JPEG quality first
        for quality in range(start_quality, min_quality - 1, -5):
            img.save(
                output_path,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True
            )

            size = os.path.getsize(output_path)

            if size <= target_bytes:
                print(
                    f"Compressed successfully: {size / 1024:.1f} KB "
                    f"at quality {quality}, size {img.size[0]}x{img.size[1]}"
                )
                return output_path

        # If still too large, resize and try again
        width = int(width * resize_step)
        height = int(height * resize_step)

        if width < min_width:
            raise ValueError(
                f"Could not compress under {target_kb} KB "
                f"without going below {min_width}px width."
            )

        img = img.resize((width, height), Image.LANCZOS)



if __name__ == "__main__":
    input_path = "/home/ogier-derouineau/Documents/edited.png"
    output_path = "/home/ogier-derouineau/Documents/edited_50kb.jpg"

    compress_image_to_target(
        input_path=input_path,
        output_path=output_path,
        target_kb=50
    )