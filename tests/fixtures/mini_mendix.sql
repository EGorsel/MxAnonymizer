-- Tiny synthetic Mendix-shaped schema used by the E2E test.
-- Mirrors the conventions: module$entity, *_assoc_*, system$* tables.

DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public;

CREATE TABLE public."system$user" (
    id uuid PRIMARY KEY,
    "Name" text NOT NULL,
    "Email" text,
    "FullName" text,
    "Password" text,
    "Active" boolean DEFAULT true,
    "Blocked" boolean DEFAULT false
);

CREATE TABLE public."system$role" (
    id uuid PRIMARY KEY,
    "Name" text NOT NULL
);

CREATE TABLE public."system$user_roles" (
    "system$userid" uuid REFERENCES public."system$user"(id),
    "system$roleid" uuid REFERENCES public."system$role"(id)
);

CREATE TABLE public."system$filedocument" (
    id uuid PRIMARY KEY,
    "Name" text,
    "HasContents" boolean DEFAULT false,
    "Size" bigint DEFAULT 0,
    "Contents" bytea
);

CREATE TABLE public."system$session" (
    id uuid PRIMARY KEY,
    "userid" uuid
);

CREATE TABLE public."crm$customer" (
    id uuid PRIMARY KEY,
    "Firstname" text,
    "Lastname" text,
    "Email" text UNIQUE,
    "Phonenumber" text,
    "BSN" text,
    "IBAN" text,
    "Kenteken" text,
    "DateOfBirth" date,
    "Notes" text,
    "Street" text,
    "Huisnummer" integer,
    "Postcode" text,
    "City" text,
    "Country" text
);

CREATE TABLE public."crm$claim" (
    id uuid PRIMARY KEY,
    "ClaimNumber" text,
    "Description" text,
    "customerId" uuid REFERENCES public."crm$customer"(id)
);

CREATE TABLE public."crm$customer_assoc_claim" (
    "crm$customerid" uuid REFERENCES public."crm$customer"(id),
    "crm$claimid" uuid REFERENCES public."crm$claim"(id)
);

-- Seed data with realistic-looking PII so leak checks have something to detect.
INSERT INTO public."system$role" (id, "Name") VALUES
    ('11111111-1111-1111-1111-111111111111', 'Administrator'),
    ('22222222-2222-2222-2222-222222222222', 'User');

INSERT INTO public."system$user" (id, "Name", "Email", "FullName", "Password") VALUES
    ('33333333-3333-3333-3333-333333333333', 'admin@anwb.nl', 'admin@anwb.nl', 'Admin User', '$2b$10$realhashplaceholder.................................'),
    ('44444444-4444-4444-4444-444444444444', 'jdoe', 'j.doe@anwb.com', 'Jan de Vries', '$2b$10$another.................................................');

INSERT INTO public."system$user_roles" VALUES
    ('33333333-3333-3333-3333-333333333333', '11111111-1111-1111-1111-111111111111'),
    ('44444444-4444-4444-4444-444444444444', '22222222-2222-2222-2222-222222222222');

INSERT INTO public."system$filedocument" (id, "Name", "HasContents", "Size", "Contents") VALUES
    ('55555555-5555-5555-5555-555555555555', 'passport_scan.pdf', true, 12345, decode('deadbeef', 'hex'));

INSERT INTO public."system$session" (id, "userid") VALUES
    ('66666666-6666-6666-6666-666666666666', '33333333-3333-3333-3333-333333333333');

INSERT INTO public."crm$customer"
    (id, "Firstname", "Lastname", "Email", "Phonenumber", "BSN", "IBAN", "Kenteken",
     "DateOfBirth", "Notes", "Street", "Huisnummer", "Postcode", "City", "Country") VALUES
    ('aaaa1111-1111-1111-1111-111111111111', 'Jan', 'de Vries', 'jan.devries@anwb.nl',
     '+31612345678', '123456782', 'NL91INGB0417164300', '12-ABC-3',
     '1980-05-15', 'Customer called about claim', 'Wassenaarseweg', 220, '2596 EC', 'Den Haag', 'Nederland'),
    ('aaaa2222-2222-2222-2222-222222222222', 'Marieke', 'van Dijk', 'm.vandijk@anwb.com',
     '+31698765432', '111222333', 'NL20RABO0300065264', '99-XYZ-1',
     '1992-11-30', 'VIP customer', 'Hoofdstraat', 12, '1000 AA', 'Amsterdam', 'Nederland');

INSERT INTO public."crm$claim" (id, "ClaimNumber", "Description", "customerId") VALUES
    ('bbbb1111-1111-1111-1111-111111111111', 'CL-001', 'Pechhulp on A12, customer Jan de Vries called from +31612345678', 'aaaa1111-1111-1111-1111-111111111111');

INSERT INTO public."crm$customer_assoc_claim" VALUES
    ('aaaa1111-1111-1111-1111-111111111111', 'bbbb1111-1111-1111-1111-111111111111');
