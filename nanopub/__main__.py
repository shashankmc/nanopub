#! /usr/bin/env python3
import os
import re
import shutil
from pathlib import Path
from typing import Tuple, Union

import click
import rdflib

from nanopub import Nanopub, NanopubConfig, load_profile, namespaces
from nanopub.definitions import DEFAULT_PROFILE_PATH, USER_CONFIG_DIR, MalformedNanopubError
from nanopub.profile import Profile, ProfileError, generate_keys

PRIVATE_KEY_FILE = 'id_rsa'
PUBLIC_KEY_FILE = 'id_rsa.pub'
DEFAULT_KEYS_PATH_PREFIX = USER_CONFIG_DIR / 'id'
DEFAULT_PRIVATE_KEY_PATH = USER_CONFIG_DIR / PRIVATE_KEY_FILE
DEFAULT_PUBLIC_KEY_PATH = USER_CONFIG_DIR / PUBLIC_KEY_FILE
RSA = 'RSA'
ORCID_ID_REGEX = r'^https://orcid.org/(\d{4}-){3}\d{3}(\d|X)$'


def validate_orcid_id(ctx, param, orcid_id: str):
    """
    Check if valid ORCID iD, should be https://orcid.org/ + 16 digit in form:
        https://orcid.org/0000-0000-0000-0000. ctx and param are
        necessary `click` callback arguments
    """
    if re.match(ORCID_ID_REGEX, orcid_id):
        return orcid_id
    else:
        raise ValueError('Your ORCID iD is not valid, please provide a valid ORCID iD that '
                         'looks like: https://orcid.org/0000-0000-0000-0000')


@click.group()
def cli():
    """Nanopub Command Line Interface"""


@cli.command(help='Get the current profile')
def profile():
    """Get the current user profile info."""
    try:
        p = load_profile()
        click.echo(f' 👤 User profile in \033[1m{DEFAULT_PROFILE_PATH}\033[0m')
        click.echo(str(p))
    except ProfileError:
        click.echo(f" ⚠️  No profile could be loaded from {DEFAULT_PROFILE_PATH}")
        click.echo(" ℹ️  Use \033[1mnp setup\033[0m to setup your nanopub profile locally with the interactive CLI")



@cli.command(help='Sign a Nanopublication')
@click.argument('filepath', type=Path)
@click.option('-k', '--private-key', nargs=2, type=Path,
              help='Your RSA private keys with which your nanopubs will be signed',
              default=None)
def sign(filepath: Path, private_key: Path):
    if private_key:
        config = NanopubConfig(
            profile=Profile(
                # TODO: better handle Profile without name or orcid_id
                name='', orcid_id='',
                private_key=private_key
            ),
        )
    else:
        config = NanopubConfig(profile=load_profile())

    folder_path, filename = os.path.split(filepath)
    np = Nanopub(
        config=config,
        rdf=filepath
    )
    np.sign()
    signed_filepath = f"{str(folder_path)}/signed.{str(filename)}"
    np.rdf.serialize(signed_filepath, format='trig')
    click.echo(f" ✒️  Nanopub signed in \033[1m{signed_filepath}\033[0m with the trusty URI \033[1m{np.source_uri}\033[0m")
    click.echo(f" 📬️ To publish it run \033[1mnp publish {signed_filepath}\033[0m")


@cli.command(help='Publish a Nanopublication')
@click.argument('filepath', type=Path)
@click.option('--test', is_flag=True, default=False,
              help='Prompt questions to generate the dataset metadata and analyze the endpoint (default), or only analyze')
def publish(filepath: Path, test: bool):
    if test:
        click.echo("Publishing to test server")
    config = NanopubConfig(
        profile=load_profile(),
        use_test_server=test,
    )
    np = Nanopub(config=config, rdf=filepath)
    np.publish()
    click.echo(f" 📬️ Nanopub published at \033[1m{np.source_uri}\033[0m")



@cli.command(help='Check if a signed Nanopublication is valid')
@click.argument('filepath', type=Path)
def check(filepath: Path):
    config = NanopubConfig(profile=load_profile())
    np = Nanopub(config=config, rdf=filepath)
    try:
        np.is_valid
        click.echo(f"\033[1m✅ Valid nanopub\033[0m {np.source_uri}")
    except MalformedNanopubError as e:
        click.echo(f"\033[1m❌ Invalid nanopub\033[0m: {e}")



@cli.command(help='Interactive CLI to create a nanopub user profile. '
                  'A local version of the profile will be stored in the user config dir '
                  '(by default HOMEDIR/.nanopub/). '
                  'The profile will also be published to the nanopub servers.')
@click.option('--keypair', nargs=2, type=Path,
              help='Your RSA public and private keys with which your nanopubs will be signed',
              default=None)
@click.option('--newkeys', type=bool, is_flag=True, default=False,
              help='Generate new RSA public and private keys with which your nanopubs will be '
                   'signed')
@click.option('--orcid_id', type=str,
              prompt='What is your ORCID iD (i.e. https://orcid.org/0000-0000-0000-0000)?',
              help='Your ORCID iD (i.e. https://orcid.org/0000-0000-0000-0000)',
              callback=validate_orcid_id)
@click.option('--name', type=str, prompt='What is your full name?', help='Your full name')
@click.option('--publish/--no-publish', type=bool, is_flag=True, default=True,
              help='If true, nanopub will be published to nanopub servers',
              prompt=('Would you like to publish your profile to the nanopub servers? '
                      'This links your ORCID iD to your RSA key, thereby making all your '
                      'publications linkable to you'))
def setup(orcid_id, publish, newkeys, name, keypair: Union[Tuple[Path, Path], None]):
    """
    Interactive CLI to create a user profile.

    Args:
        orcid_id: the users ORCID iD or other form of universal identifier. Example:
            `https://orcid.org/0000-0000-0000-0000`
        publish: if True, profile will be published to nanopub servers
        name: the name of the user
        keypair: a tuple containing the paths to the public and private RSA key to be used to sign
            nanopubs. If empty, new keys will be generated or the ones in the .nanopub folder
            will be used.
    """
    click.echo('Setting up nanopub profile...')
    if not USER_CONFIG_DIR.exists():
        USER_CONFIG_DIR.mkdir()

    if not keypair and not newkeys:
        prompt = 'Provide the path to your public RSA key: ' \
                 f'Leave empty for using the one in {USER_CONFIG_DIR}'
        public_key = click.prompt(prompt, type=Path, default="")
        if not public_key:
            keypair = None
        else:
            prompt = 'Provide the path to your private RSA key: '
            private_key = click.prompt(prompt, type=Path)
            keypair = public_key, private_key

    if not keypair:
        if _rsa_keys_exist():
            click.echo(f'RSA keys already exist and are stored in {USER_CONFIG_DIR}. '
                       f'If you want to create new ones then you must manually '
                       f'delete these keys.')
        else:
            # JavaWrapper().make_keys(path_name=DEFAULT_KEYS_PATH_PREFIX)
            generate_keys(USER_CONFIG_DIR)
            click.echo(f'Created RSA keys. Your RSA keys are stored in {USER_CONFIG_DIR}')
    else:
        public_key_path, private_key = keypair

        # Copy the keypair to the default location
        shutil.copy(public_key_path, USER_CONFIG_DIR / PUBLIC_KEY_FILE)
        shutil.copy(private_key, USER_CONFIG_DIR / PRIVATE_KEY_FILE)

        click.echo(f'Your RSA keys have been copied to {USER_CONFIG_DIR}')

    # Public key can always be found at DEFAULT_PUBLIC_KEY_PATH.
    # Either new keys have been generated there or
    # existing keys have been copy to that location.
    public_key = DEFAULT_PUBLIC_KEY_PATH.read_text()

    profile = Profile(orcid_id, name, DEFAULT_PUBLIC_KEY_PATH, DEFAULT_PRIVATE_KEY_PATH)
    profile.store_profile(USER_CONFIG_DIR)


    # Declare the user to nanopub
    if publish:
        assertion, concept = _create_this_is_me_rdf(orcid_id, public_key, name)
        np = Nanopub(
            assertion=assertion,
            config=NanopubConfig(
                assertion_attributed_to=orcid_id,
                profile=profile
            ),
            introduces_concept=concept,
        )

        # client = NanopubClient()
        # result = client.publish(np)
        np.publish()

        profile.introduction_nanopub_uri = np.concept_uri

        # Store profile nanopub uri
        profile.store_profile(USER_CONFIG_DIR)


def _create_this_is_me_rdf(orcid_id: str, public_key: str, name: str
                           ) -> Tuple[rdflib.Graph, rdflib.BNode]:
    """
    Create a set of RDF triples declaring the existence of the user with associated ORCID iD.
    """
    assertion = rdflib.Graph()
    assertion.bind('foaf', rdflib.FOAF)
    assertion.bind("npx", namespaces.NPX)

    key_declaration = rdflib.BNode('keyDeclaration')
    orcid_node = rdflib.URIRef(orcid_id)

    assertion.add((key_declaration, namespaces.NPX.declaredBy, orcid_node))
    assertion.add((key_declaration, namespaces.NPX.hasAlgorithm, rdflib.Literal(RSA)))
    assertion.add((key_declaration, namespaces.NPX.hasPublicKey, rdflib.Literal(public_key)))
    assertion.add((orcid_node, rdflib.FOAF.name, rdflib.Literal(name)))

    return assertion, key_declaration


def _rsa_keys_exist():
    return DEFAULT_PRIVATE_KEY_PATH.exists() or DEFAULT_PUBLIC_KEY_PATH.exists()


# def _check_erase_existing_keys():
#     return click.confirm('It seems you already have RSA keys for nanopub. '
#                          'Would you like to replace them?',
#                          default=False)


if __name__ == '__main__':
    cli()
