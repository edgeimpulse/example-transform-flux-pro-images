import os
import sys
import shutil
import requests
import argparse
import json
import time
import traceback
import replicate 

if not os.getenv('RP_API_TOKEN'):
    print('Missing RP_API_TOKEN')
    sys.exit(1)

if not os.getenv('EI_PROJECT_API_KEY'):
    print('Missing EI_PROJECT_API_KEY')
    sys.exit(1)

RP_API_TOKEN = os.environ.get("RP_API_TOKEN")
API_KEY = os.environ.get("EI_PROJECT_API_KEY")
INGESTION_HOST = os.environ.get("EI_INGESTION_HOST", "edgeimpulse.com")

parser = argparse.ArgumentParser(
    description='Use Replicate to generate an image dataset for classification from your prompt')

parser.add_argument('--prompt', type=str, required=True, help="Prompt to generate the images")
parser.add_argument('--label', type=str, required=True, help="Label for the images")
parser.add_argument('--images', type=int, required=True, help="Number of images to generate")
parser.add_argument('--upload-category', type=str, required=False,
                    help="Which category to upload data to in Edge Impulse", default='split')
parser.add_argument('--synthetic-data-job-id', type=int, required=False,
                    help="If specified, sets the synthetic_data_job_id metadata key")
parser.add_argument('--skip-upload', action='store_true', required=False, help="Skip uploading to EI")
parser.add_argument('--out-directory', type=str, required=False, help="Directory to save images to", default="output")

parser.add_argument('--aspect-ratio', type=str, default='1:1',
                    help="Aspect ratio for the generated image (e.g., '1:1', '16:9')")
parser.add_argument('--steps', type=int, default=27,
                    help="Number of diffusion steps (1-50)")
parser.add_argument('--guidance', type=float, default=4.34,
                    help="Controls the balance between adherence to the text prompt and image quality/diversity (2-5)")
parser.add_argument('--interval', type=float, default=1.27,
                    help="Increases variance in outputs (1-4)")
parser.add_argument('--safety-tolerance', type=int, default=2,
                    help="Safety tolerance, 1 is most strict and 5 is most permissive")
parser.add_argument('--output-format', type=str, default='png',
                    help="Format of the output images (e.g., 'png', 'jpeg')")

args, unknown = parser.parse_known_args()

INGESTION_URL = f"https://ingestion.{INGESTION_HOST}"
if INGESTION_HOST.endswith('.test.edgeimpulse.com'):
    INGESTION_URL = f"http://ingestion.{INGESTION_HOST}"
if INGESTION_HOST == 'host.docker.internal':
    INGESTION_URL = f"http://{INGESTION_HOST}:4810"

if os.path.exists(args.out_directory):
    shutil.rmtree(args.out_directory)
os.makedirs(args.out_directory)

epoch = int(time.time())

print('Prompt:', args.prompt)
print('Number of images:', args.images)
print('')

replicate_client = replicate.Client(api_token=RP_API_TOKEN)

def generate_image(prompt):
    inputs = {
        "prompt": prompt,
        "aspect_ratio": args.aspect_ratio,
        "steps": args.steps,
        "guidance": args.guidance,
        "interval": args.interval,
        "safety_tolerance": args.safety_tolerance,
        "output_format": args.output_format,
    }

    output = replicate_client.run(
        "black-forest-labs/flux-pro",
        input=inputs
    )
    print("Received output from Replicate:", output)

    if output:
        if isinstance(output, list):
            output_url = output[0]
        elif isinstance(output, str):
            output_url = output
        else:
            raise Exception("Unexpected output type received from the model.")
    else:
        raise Exception("No output URL received from the model.")

    try:
        response = requests.get(output_url)
        response.raise_for_status()
        image_bytes = response.content
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to download image from {output_url}: {e}")

    return image_bytes

MAX_RETRIES = 3
MAX_DELAY = 60

for i in range(args.images):
    unique_prompt = args.prompt
    print(f'Creating image {i + 1} of {args.images} for {args.label}...', end='', flush=True)

    retries = 0
    success = False

    while retries < MAX_RETRIES and not success:
        try:
            image_bytes = generate_image(unique_prompt)
            filename = f'{args.label}.{epoch}.{i}.{args.output_format}'
            fullpath = os.path.join(args.out_directory, filename)

            with open(fullpath, 'wb+') as f:
                f.write(image_bytes)

            metadata = {
                'generated_by': 'replicate',
                'prompt': unique_prompt
            }

            if not args.skip_upload:
                headers = {
                    'x-label': args.label,
                    'x-api-key': API_KEY,
                    'x-metadata': json.dumps(metadata)
                }
                if args.synthetic_data_job_id is not None:
                    headers['x-synthetic-data-job-id'] = str(args.synthetic_data_job_id)

                res = requests.post(
                    url=f'{INGESTION_URL}/api/{args.upload_category}/files',
                    headers=headers,
                    files={'data': (os.path.basename(fullpath), image_bytes, f'image/{args.output_format}')}
                )

                if res.status_code != 200:
                    raise Exception(
                        f'Failed to upload file to Edge Impulse (status_code={res.status_code}): '
                        f'{res.content.decode("utf-8")}'
                    )
                else:
                    body = json.loads(res.content.decode("utf-8"))
                    if not body['success']:
                        raise Exception(f'Failed to upload file to Edge Impulse: {body["error"]}')
                    if not body['files'][0]['success']:
                        raise Exception(f'Failed to upload file to Edge Impulse: {body["files"][0]["error"]}')

            print(' OK')
            success = True

        except Exception as e:
            retries += 1
            print(f'\nFailed to complete image generation on attempt {retries} for image {i + 1}: {e}')
            print(traceback.format_exc())

            if retries < MAX_RETRIES:
                delay = min(3 ** retries, MAX_DELAY)
                print(f'Waiting for {delay} seconds before retrying...')
                time.sleep(delay)
                print('Retrying...')
            else:
                print(f'Max retries reached for image {i + 1}. Skipping to next image.')
                break